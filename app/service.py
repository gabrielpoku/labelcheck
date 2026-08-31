"""End-to-end pipeline: image bytes -> OCR -> field verification."""
from __future__ import annotations

import time

from app.engine.models import ApplicationData, VerificationResult, Verdict
from app.engine.verify import verify_label
from app.ocr.engine import ocr_image_bytes


def verify_image(application: ApplicationData, image_bytes: bytes) -> VerificationResult:
    start = time.perf_counter()
    ocr_lines = ocr_image_bytes(image_bytes)
    checks = verify_label(application, [line.text for line in ocr_lines])
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    result = VerificationResult(
        application_id=application.application_id,
        overall=Verdict.MATCH,  # replaced with the roll-up below
        checks=checks,
        elapsed_ms=elapsed_ms,
        ocr_text="\n".join(line.text for line in ocr_lines),
    )
    # A label is only as good as its worst field.
    result.overall = result.worst
    return result
