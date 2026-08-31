"""OCR layer.

RapidOCR (ONNX runtime) runs entirely on the server: no cloud vision APIs, no
outbound network calls. That matters here because the deployment network may
restrict outbound traffic.

The engine is a process-wide singleton (model loading takes ~1s; a warmup call
at startup keeps the first real request fast enough for the 5-second budget).
"""
from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

_MAX_DIM = 1600        # downscale huge artwork; OCR accuracy holds, speed improves
_MIN_DIM = 700         # upscale tiny photos so small print is legible to OCR


@dataclass
class OcrLine:
    text: str
    confidence: float
    y: float            # top edge, used to sort blocks top-to-bottom
    x: float


class LabelOcr:
    """Thread-safe OCR wrapper.

    A small semaphore (rather than a hard lock) allows two OCR passes in
    flight. Batch throughput roughly doubles while interactive single-label
    latency is unaffected (onnxruntime releases the GIL during inference).
    """

    def __init__(self, concurrency: int = 2) -> None:
        self._slots = threading.BoundedSemaphore(concurrency)
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR()

    def warmup(self) -> None:
        """Run OCR passes at startup so ONNX graphs, thread pools and memory
        arenas are hot before the first user request. The 5-second budget
        applies from request #1, and an unwarmed first pass costs several
        extra seconds.

        Warms on a real bundled label rather than a synthetic one: the
        recognition stage allocates per text-box, so a sparse image leaves
        most of that cost for the first genuine request to pay.
        """
        for image_bytes in self._warmup_images():
            self.read_lines_from_image(load_image_bytes(image_bytes))

    @staticmethod
    def _warmup_images() -> list[bytes]:
        sample = Path(__file__).resolve().parent.parent.parent / "samples" / "bourbon_ok.png"
        if sample.exists():
            data = sample.read_bytes()
            return [data, data]

        # No samples shipped: fall back to synthetic artwork of the same shape.
        from PIL import ImageDraw

        img = Image.new("RGB", (620, 970), "white")
        draw = ImageDraw.Draw(img)
        draw.text((40, 40), "OLD TOM DISTILLERY 45% ALC./VOL. (90 PROOF) 750 mL", fill="black")
        draw.text((40, 900), "GOVERNMENT WARNING: (1) According to the Surgeon General", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return [buf.getvalue(), buf.getvalue()]

    def read_lines_from_image(self, img_array: np.ndarray) -> list[OcrLine]:
        with self._slots:
            result, _ = self._engine(img_array)
        lines: list[OcrLine] = []
        if result:
            for box, text, score in result:
                ys = [p[1] for p in box]
                xs = [p[0] for p in box]
                lines.append(OcrLine(text=text, confidence=float(score), y=min(ys), x=min(xs)))
        # Reading order: top-to-bottom, then left-to-right within a band.
        lines.sort(key=lambda l: (round(l.y / 18.0), l.x))
        return lines


def load_image_bytes(image_bytes: bytes) -> np.ndarray:
    """Decode upload bytes and normalize resolution for OCR speed/accuracy."""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > _MAX_DIM:
        scale = _MAX_DIM / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    elif min(w, h) < _MIN_DIM:
        scale = min(_MIN_DIM / min(w, h), 4.0)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return np.asarray(img)


_ocr: LabelOcr | None = None
_ocr_lock = threading.Lock()


def get_ocr() -> LabelOcr:
    global _ocr
    with _ocr_lock:
        if _ocr is None:
            _ocr = LabelOcr()
        return _ocr


def ocr_image_bytes(image_bytes: bytes) -> list[OcrLine]:
    return get_ocr().read_lines_from_image(load_image_bytes(image_bytes))
