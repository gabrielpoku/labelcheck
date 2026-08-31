# LabelCheck

A prototype web app for TTB's Compliance Division. An agent uploads label
artwork plus the application data for that label (or a CSV of many labels at
once); the app reads the label with OCR, checks each mandatory field, and
returns a per-field verdict in a couple of seconds.

Built for the take-home brief at `treasurytakehome-rgb/instructions`.

**Live app:** _(add the deployed URL here)_

## What it checks

| Mandatory label field | Rule |
|---|---|
| Brand name | Fuzzy match. Case differences alone never fail a field. |
| Class / type designation | Fuzzy match. |
| Alcohol content | Parses `% ALC./VOL.`, `ABV` and `PROOF` (US proof = 2x ABV), and cross-checks proof against ABV on the label itself. |
| Net contents | Parses mL / L / fl oz and compares in mL. |
| Bottler/producer name and address | Fuzzy match. Common street abbreviations are expanded on both sides, so "Blvd." matches "Boulevard". |
| Country of origin | Imports only. Looks for "Product of ..." statements. |
| Government Warning | Word-for-word comparison against the 27 CFR 16.21 text. "GOVERNMENT WARNING:" must be all caps. |

Each field gets one of four verdicts:

- **OK**: matches the application.
- **REVIEW**: close but not identical, e.g. one OCR-noisy character in the
  warning, or 45.0% vs 45.3% ABV. These are never auto-failed; a person decides.
- **MISMATCH**: clearly disagrees with the application.
- **NOT ON LABEL**: a mandatory field could not be found at all. Counts as a failure.

The overall result is the worst field verdict. The UI shows expected vs. found
text for every field, the raw OCR transcript, and the processing time.

## How the brief shaped the build

**Speed.** Sarah Chen's line was "If we can't get results back in about 5
seconds, nobody's going to use it." OCR runs locally through ONNX Runtime
(RapidOCR). On a laptop-class CPU a single label lands around 1.5 to 3 seconds.
The slowest of the bundled samples is the deliberately bad photograph, which
takes about 4.5 seconds and still comes in under the limit. Every result prints
its own elapsed time, so the number is never something you have to take on
faith. The models are loaded and warmed on a real label at server startup,
which keeps the first request in the same range as the hundredth.

**Simplicity.** "We need something my mother could figure out." One page, two
tabs, no jargon, large type. The verdict reads as a sentence ("Match: label
agrees with the application") before it reads as a status chip. Built-in sample
labels are one click away so a new user gets a real result immediately.

**Judgment, not pattern matching.** Dave Morrison's point was that a difference
can be "technically a mismatch? Sure. But it's obviously the same thing."
Comparison folds case, accents and punctuation before scoring, and the fuzzy
scores have a REVIEW band in the middle. Near-matches are surfaced for a person
to decide, never silently passed and never silently failed.

**The warning statement.** Jenny Park flagged that it has to be exact,
including "all caps and bold". The checker walks the OCR tokens against the
canonical word sequence and reports any missing, extra or substituted word.
Word merges and single-character misreads are classified as OCR artifacts and
downgraded to REVIEW rather than failed. The all-caps header is verified from
the OCR casing. Bold cannot be recovered from OCR at all, so every warning
result carries a note asking the reviewer to confirm boldness on the image.
That seemed better than quietly pretending the check was done.

**Batch.** The brief calls for 200 to 300 applications at a time. The batch tab
takes one CSV of application data plus all the label images, runs as a
background job with a live progress bar, and produces a summary table and a
downloadable CSV report.

**Network restrictions.** Marcus Williams noted that outbound traffic is a
constraint. There are no cloud APIs anywhere in this app. OCR is local, fuzzy
matching is local (RapidFuzz), and the app makes no outbound calls at runtime.
It is also standalone, with no COLA integration, per his note that COLA is "a
whole different beast with its own authorization requirements."

**Bad photographs.** Jenny Park mentioned odd angles, poor lighting and glare.
`imperfect_photo` in the samples is a label shot at an angle with glare over
it. Every quantity field still verifies; the warning lands in REVIEW with the
specific OCR artifacts listed.

## Running locally

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

The app serves at http://127.0.0.1:8000.

The sample labels are committed, but you can regenerate the artwork with
`python -m app.samples.generator`.

### Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

`test_normalize.py`, `test_parsers.py`, `test_warning.py` and `test_verify.py`
are unit tests for the comparison engine. They involve no OCR and are fully
deterministic. `test_api.py` drives the real thing end to end: real OCR on the
generated sample labels through the HTTP API, the batch flow, and an assertion
that single-label verification stays inside the 5-second budget.

## API

- `POST /api/verify`: multipart, `image` (PNG/JPEG/WebP) plus `application` (JSON).
  Returns per-field checks, overall verdict, elapsed time and the OCR transcript.
- `POST /api/batch`: multipart, `csv_file` plus `images[]`. Returns `{job_id, total}`.
- `GET /api/batch/{job_id}`: progress and results. Jobs expire after 30 minutes.
- `GET /api/samples`, `GET /api/samples/{name}/image`: the bundled demo labels.

Batch CSV columns (`samples/applications.csv` is a working example):
`image_filename, brand_name, class_type, alcohol_pct, net_contents_ml,
bottler_name, bottler_address, is_import, country_of_origin, application_id`.
The last two are optional.

## Project layout

```
app/
  engine/        comparison logic: models, normalization, parsers, fuzzy
                 verification, warning checker. No OCR, fully unit-tested.
  ocr/           RapidOCR wrapper and image preprocessing
  samples/       generator for the demo label artwork
  main.py        FastAPI app: verify, batch jobs, samples
  service.py     image -> OCR -> verdict pipeline
static/          single-page frontend, no build step
samples/         generated demo labels, applications.csv, index.json
tests/           unit and integration tests
```

Keeping the engine free of any OCR dependency is the main structural decision.
Every rule can be tested against a hand-written OCR transcript, which is what
makes the edge cases (merged words, mis-cased headers, proof/ABV disagreement)
cheap to cover.

## Deployment

Any host that runs a Python container works. A `Dockerfile` and a `render.yaml`
are included.

```bash
docker build -t labelcheck .
docker run -p 8000:8000 labelcheck
```

Then visit http://localhost:8000. The image has no external dependencies, so
Railway, Fly, Cloud Run or Azure Container Apps work the same way.

## Assumptions and trade-offs

1. **One label image per application.** Real COLA submissions can include
   several views. This prototype takes the single artwork file carrying all
   mandatory statements, which is standard for distilled spirits labels.
2. **Bold type is not machine-verified.** OCR recovers text, not typography.
   The tool verifies wording and the all-caps header and asks the reviewer to
   confirm boldness, rather than faking a check it cannot do.
3. **Tolerances.** ABV: differences of 0.05 percentage points or less match,
   0.5 or less go to REVIEW as rounding or typo territory, larger differences
   are a mismatch. Net contents tolerance is 1%.
4. **Verdicts, not approvals.** The tool surfaces agreements and discrepancies.
   Final judgment stays with an agent.
5. **Batch concurrency** is capped at 2 OCR passes in flight so a large batch
   cannot starve someone checking a single label. A 300-label batch takes
   minutes, and progress is visible throughout.
6. **English labels only.** The OCR model is multilingual but the field
   grammars (ALC./VOL., PROOF, "Product of ...") are US English.
7. **Nothing is stored.** Uploads are processed in memory and never written to
   disk. Batch jobs live in RAM and expire after 30 minutes.
8. **Sample labels are generated artwork**, not real submissions. They exist to
   exercise every verdict path deterministically.
