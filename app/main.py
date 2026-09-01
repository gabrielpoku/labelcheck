"""FastAPI application: single-label verification, batch jobs, and bundled samples.

Uploads are processed in memory and never written to disk. Batch jobs live in
an in-memory store and expire, so no label artwork or application data is
persisted anywhere.
"""
from __future__ import annotations

import csv
import io
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.engine.models import ApplicationData, VerificationResult
from app.ocr.engine import _ocr_concurrency
from app.service import verify_image

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
BATCH_MAX_ITEMS = 500
JOB_TTL_SECONDS = 30 * 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load OCR models once so the first real request stays inside the 5s budget.
    from app.ocr.engine import get_ocr

    get_ocr().warmup()
    yield


app = FastAPI(
    title="LabelCheck: Alcohol Label Verification (POC)",
    version="1.0.0",
    lifespan=lifespan,
)


# Single-label verification

async def _read_image(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is larger than 10 MB. Please provide a smaller file.")
    if file.content_type and file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(415, f"Unsupported image type '{file.content_type}'. Use PNG, JPEG, or WebP.")
    if not data:
        raise HTTPException(400, "Empty image file.")
    return data


@app.post("/api/verify")
async def verify_endpoint(
    image: UploadFile = File(..., description="Label artwork (PNG/JPEG/WebP)"),
    application: str = Form(..., description="Application data as JSON"),
) -> VerificationResult:
    try:
        app_data = ApplicationData.model_validate(json.loads(application))
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Application data is not valid JSON: {exc}") from exc
    except Exception as exc:
        raise HTTPException(400, f"Application data is invalid: {exc}") from exc

    image_bytes = await _read_image(image)
    return verify_image(app_data, image_bytes)


# Batch verification (in-memory job with progress polling)

class BatchJob:
    def __init__(self, total: int) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.created_at = time.time()
        self.total = total
        self.done = 0
        self.results: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.status = "processing"
        self.lock = threading.Lock()

    def record(self, outcome: dict[str, Any]) -> None:
        with self.lock:
            if outcome.get("overall") == "error":
                self.errors.append(outcome)
            else:
                self.results.append(outcome)
            self.done += 1

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "job_id": self.id,
                "status": self.status,
                "total": self.total,
                "done": self.done,
                "results": self.results,
                "errors": self.errors,
            }


_jobs: dict[str, BatchJob] = {}
_jobs_lock = threading.Lock()
# Worker pool for OCR work (onnxruntime releases the GIL, so threads scale).
# Sized to the OCR concurrency so at most that many rows are decoded and
# processed end-to-end at once — on a 512 MB instance every concurrent row
# holds decoded image buffers and OCR activations, so this directly sets the
# batch's memory ceiling.
_row_pool = ThreadPoolExecutor(max_workers=_ocr_concurrency())


def _prune_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    stale = [k for k, v in _jobs.items() if v.created_at < cutoff]
    for k in stale:
        del _jobs[k]


def _parse_batch_csv(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"image_filename", "brand_name"}
    missing = required - {h.strip() for h in (reader.fieldnames or [])}
    if missing:
        raise ValueError(f"Batch CSV is missing required column(s): {', '.join(sorted(missing))}")
    return [
        {(k or "").strip(): (v or "") for k, v in row.items()} for row in reader
    ]


def _row_to_application(row: dict[str, str]) -> ApplicationData:
    def get(key: str) -> str:
        val = (row.get(key) or "").strip()
        if not val:
            raise ValueError(f"Missing value for '{key}'")
        return val

    is_import = (row.get("is_import") or "").strip().lower() in {"true", "yes", "1", "y"}
    return ApplicationData(
        application_id=(row.get("application_id") or "").strip() or None,
        brand_name=get("brand_name"),
        **{"class/type": get("class_type")},
        alcohol_pct=float(get("alcohol_pct")),
        net_contents_ml=float(get("net_contents_ml")),
        bottler_name=get("bottler_name"),
        bottler_address=get("bottler_address"),
        is_import=is_import,
        country_of_origin=(row.get("country_of_origin") or "").strip() or None,
    )


@app.post("/api/batch")
async def start_batch(
    csv_file: UploadFile = File(..., description="CSV of application data"),
    images: list[UploadFile] = File(..., description="Label artwork files referenced by the CSV"),
) -> dict[str, Any]:
    csv_text = (await csv_file.read()).decode("utf-8-sig")
    try:
        rows = _parse_batch_csv(csv_text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not rows:
        raise HTTPException(400, "Batch CSV contains no application rows.")
    if len(rows) > BATCH_MAX_ITEMS:
        raise HTTPException(400, f"Batch limited to {BATCH_MAX_ITEMS} applications in this prototype.")

    image_map: dict[str, bytes] = {}
    for img in images:
        image_map[img.filename] = await _read_image(img)

    job = BatchJob(total=len(rows))
    with _jobs_lock:
        _prune_jobs()
        _jobs[job.id] = job

    threading.Thread(target=_run_batch, args=(job, rows, image_map), daemon=True).start()
    return {"job_id": job.id, "total": job.total}


def _run_batch(job: BatchJob, rows: list[dict[str, str]], image_map: dict[str, bytes]) -> None:
    def work(row: dict[str, str]) -> dict[str, Any]:
        try:
            app_data = _row_to_application(row)
            image_name = row.get("image_filename", "").strip()
            image_bytes = image_map.get(image_name)
            if image_bytes is None:
                return {
                    "application_id": app_data.application_id or image_name,
                    "image": image_name,
                    "overall": "error",
                    "error": f"Image '{image_name}' was not uploaded.",
                }
            result = verify_image(app_data, image_bytes).model_dump()
            result["image"] = image_name
            return result
        except Exception as exc:  # record per-row failures, keep the batch alive
            return {
                "application_id": row.get("application_id") or row.get("image_filename"),
                "image": row.get("image_filename"),
                "overall": "error",
                "error": str(exc),
            }

    for outcome in _row_pool.map(work, rows):
        job.record(outcome)
    job.status = "complete"


@app.get("/api/batch/{job_id}")
def batch_status(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Batch job not found or expired (results are kept for 30 minutes).")
    return job.snapshot()


# Bundled demo samples

@app.get("/api/samples")
def list_samples() -> Any:
    index_file = SAMPLES_DIR / "index.json"
    if not index_file.exists():
        return []
    return json.loads(index_file.read_text(encoding="utf-8"))


@app.get("/api/samples/{name}/image")
def sample_image(name: str) -> FileResponse:
    safe = Path(name).name
    path = SAMPLES_DIR / f"{safe}.png"
    if not path.exists():
        raise HTTPException(404, "Sample not found.")
    return FileResponse(path, media_type="image/png")


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
