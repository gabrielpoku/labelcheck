"""Field-by-field verification of a label against its application data.

Design: this engine never runs OCR itself. It receives the OCR text lines and
the application data, and produces a verdict per mandatory field plus an
overall verdict. Keeping it OCR-free makes every rule unit-testable.

Verdict semantics:
- MATCH        Values agree (case differences alone never fail a field).
- REVIEW       Close but not identical; surfaced for human judgment. Brand
               matching in particular needs a person: a difference can be
               technically real and still obviously the same thing.
- MISMATCH     Values clearly disagree.
- NOT_FOUND    The field could not be located on the label at all. Treated as
               a failure, because every listed field is mandatory.
- NOT_APPLICABLE  Country of origin on domestic products.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from .models import ApplicationData, FieldCheck, Verdict
from .normalize import normalize_address, normalize_fold
from .parsers import ParsedAlcohol, parse_alcohol, parse_net_contents_ml
from .warning_text import CANONICAL_WARNING, check_warning

# Fuzzy thresholds. MATCH requires >= hi; hi > score >= lo is REVIEW.
_THRESHOLDS = {
    "brand": (95, 82),
    "class_type": (93, 80),
    "bottler_name": (95, 82),
    "address": (90, 72),
    "country": (92, 78),
}

# Numeric tolerances.
_ABV_MATCH_TOL = 0.05    # percentage points: 45.0 vs 45.0
_ABV_REVIEW_TOL = 0.5    # 45.0 vs 45.3: rounding/typo, worth a look
_NET_MATCH_TOL_FRAC = 0.01


def _score_lines(
    lines: list[str],
    expected: str,
    *,
    partial: bool = True,
    normalizer=normalize_fold,
) -> tuple[str | None, float]:
    """Find the OCR line most likely to contain ``expected``.

    Uses partial ratio so a line that contains the expected text plus extra
    words (e.g. brand and class merged into one OCR line) still scores high.
    OCR frequently drops the space between words ("500Harbor"), so lines are
    also compared with all spaces removed and the better score wins.
    """
    want = normalizer(expected)
    if not want or not lines:
        return None, 0.0
    scorer = fuzz.partial_ratio if partial else fuzz.ratio
    best_line, best_score = None, 0.0
    for line in lines:
        have = normalizer(line)
        score = max(
            scorer(want, have),
            scorer(want.replace(" ", ""), have.replace(" ", "")),
        )
        if score > best_score:
            best_line, best_score = line, score
    return best_line, round(best_score, 1)


def _fuzzy_check(
    field: str,
    label: str,
    expected: str,
    lines: list[str],
    *,
    normalizer=normalize_fold,
) -> FieldCheck:
    """Compare a text field against OCR lines.

    ``expected`` is the display string from the application; ``normalizer``
    produces the string actually used for scoring (e.g. addresses are
    normalized on both sides so "Blvd." matches "Boulevard").
    """
    hi, lo = _THRESHOLDS[field]
    line, score = _score_lines(lines, expected, normalizer=normalizer)
    if line is None or score < lo:
        return FieldCheck(
            field=field,
            label=label,
            verdict=Verdict.NOT_FOUND,
            expected=expected,
            found=line,
            note=f"Could not find this field on the label (best similarity {score:.0f}%).",
        )
    if score >= hi:
        verdict = Verdict.MATCH
        note = f"Matches application (similarity {score:.0f}%)."
    else:
        verdict = Verdict.REVIEW
        note = f"Close but not identical (similarity {score:.0f}%). Needs judgment."
    return FieldCheck(
        field=field, label=label, verdict=verdict, expected=expected, found=line, note=note
    )


def _check_alcohol(app: ApplicationData, lines: list[str]) -> FieldCheck:
    expected_pct = app.alcohol_pct
    # Scan every line for alcohol statements; keep the most explicit one.
    candidates: list[tuple[ParsedAlcohol, str]] = [
        (parse_alcohol(line), line) for line in lines
    ]
    candidates = [c for c in candidates if c[0].abv is not None or c[0].proof is not None]
    if not candidates:
        return FieldCheck(
            field="alcohol_content",
            label="Alcohol content",
            verdict=Verdict.NOT_FOUND,
            expected=f"{expected_pct:g}% ABV",
            found=None,
            note="No alcohol statement (e.g. \"40% ALC./VOL.\" or \"80 PROOF\") found on the label.",
        )
    # Prefer a line that has both ABV and proof, else the first with ABV.
    parsed, line = max(
        candidates, key=lambda c: (c[0].abv is not None and c[0].proof is not None, c[0].abv is not None)
    )

    notes: list[str] = []
    if not parsed.consistent:
        notes.append(
            f"Label's own proof ({parsed.proof:g}) is inconsistent with its ABV ({parsed.abv:g}%)."
        )

    diff = abs(parsed.abv - expected_pct)
    expected_disp = f"{expected_pct:g}% ABV"
    found_disp = f"{parsed.abv:g}% ABV"
    if parsed.proof is not None:
        found_disp += f" ({parsed.proof:g} proof)"

    if diff <= _ABV_MATCH_TOL and parsed.consistent:
        verdict = Verdict.MATCH
    elif diff <= _ABV_REVIEW_TOL or (diff > _ABV_MATCH_TOL and not parsed.consistent):
        verdict = Verdict.REVIEW
        notes.append(f"Application says {expected_pct:g}%, label says {parsed.abv:g}%.")
    else:
        verdict = Verdict.MISMATCH
        notes.append(f"Application says {expected_pct:g}%, label says {parsed.abv:g}%.")

    return FieldCheck(
        field="alcohol_content",
        label="Alcohol content",
        verdict=verdict,
        expected=expected_disp,
        found=found_disp,
        note=" ".join(notes) or None,
    )


def _check_net_contents(app: ApplicationData, lines: list[str]) -> FieldCheck:
    expected_ml = app.net_contents_ml
    candidates = [(parse_net_contents_ml(line), line) for line in lines]
    candidates = [(ml, line) for ml, line in candidates if ml is not None]
    if not candidates:
        return FieldCheck(
            field="net_contents",
            label="Net contents",
            verdict=Verdict.NOT_FOUND,
            expected=f"{expected_ml:g} mL",
            found=None,
            note='No net contents statement (e.g. "750 mL") found on the label.',
        )
    found_ml, line = candidates[0]
    diff_frac = abs(found_ml - expected_ml) / expected_ml
    verdict = Verdict.MATCH if diff_frac <= _NET_MATCH_TOL_FRAC else Verdict.MISMATCH
    note = (
        f"Matches application ({found_ml:g} mL)."
        if verdict is Verdict.MATCH
        else f"Application says {expected_ml:g} mL, label says {found_ml:g} mL."
    )
    return FieldCheck(
        field="net_contents",
        label="Net contents",
        verdict=verdict,
        expected=f"{expected_ml:g} mL",
        found=f"{found_ml:g} mL",
        note=note,
    )


def _check_warning(lines: list[str]) -> FieldCheck:
    # The warning is always the bottom-most mandatory block; locate the line
    # that starts it, then join everything from there to the end of the label.
    start = None
    for i, line in enumerate(lines):
        if fuzz.partial_ratio("government warning", normalize_fold(line)) >= 80:
            start = i
            break
    if start is None:
        return FieldCheck(
            field="government_warning",
            label="Government Warning",
            verdict=Verdict.NOT_FOUND,
            expected=CANONICAL_WARNING,
            found=None,
            note='No "GOVERNMENT WARNING" statement found on the label.',
        )

    found_text = " ".join(lines[start:])
    check = check_warning(found_text)
    notes: list[str] = []

    if check.header_state == "ocr_case_noise":
        notes.append(
            f'Header read as "{check.header_found}"; treated as all-caps (OCR '
            "occasionally mis-cases bold text); confirm visually."
        )
    elif check.header_state == "wrong_case":
        notes.append(
            f'Header must read "GOVERNMENT WARNING:" in all caps; label shows '
            f'"{check.header_found}".'
        )
    elif check.header_state == "missing":
        notes.append('Required "GOVERNMENT WARNING:" header was not found.')

    if check.exact and check.header_ok:
        verdict = Verdict.MATCH
        notes.append("Matches the required statement word-for-word.")
    elif check.ocr_noise_only and check.header_ok:
        verdict = Verdict.REVIEW
        notes.append("Possible OCR artifacts: " + "; ".join(check.artifacts) + ". Verify against the label image.")
    else:
        verdict = Verdict.MISMATCH
        reasons = notes + list(check.diffs)
        notes = reasons or ["Statement does not match the required wording."]
    notes.append("Bold type cannot be verified by OCR; confirm visually.")

    return FieldCheck(
        field="government_warning",
        label="Government Warning",
        verdict=verdict,
        expected=CANONICAL_WARNING,
        found=found_text,
        note=" ".join(notes),
    )


def _check_country(app: ApplicationData, lines: list[str]) -> FieldCheck:
    if not app.is_import:
        return FieldCheck(
            field="country_of_origin",
            label="Country of origin",
            verdict=Verdict.NOT_APPLICABLE,
            expected=None,
            found=None,
            note="Domestic product; country of origin statement not required.",
        )
    expected = app.country_of_origin or ""
    # Import labels phrase this as "Product of France" / "Produce of Italy" /
    # just the country name. Match against the full label text.
    joined = " ".join(lines)
    product_of = " ".join(w for w in normalize_fold(joined).split() if w not in ("product", "of", "produce"))
    score = fuzz.partial_ratio(normalize_fold(expected), product_of)
    hi, lo = _THRESHOLDS["country"]
    if score >= hi:
        return FieldCheck(
            field="country_of_origin", label="Country of origin", verdict=Verdict.MATCH,
            expected=expected, found=joined,
            note=f"Country statement found (similarity {score:.0f}%).",
        )
    if score >= lo:
        return FieldCheck(
            field="country_of_origin", label="Country of origin", verdict=Verdict.REVIEW,
            expected=expected, found=joined,
            note=f"Country statement is close but not identical (similarity {score:.0f}%). Needs judgment.",
        )
    return FieldCheck(
        field="country_of_origin", label="Country of origin", verdict=Verdict.NOT_FOUND,
        expected=expected, found=None,
        note=f'No country of origin statement (e.g. "Product of {expected}") found on the label.',
    )


def verify_label(app: ApplicationData, ocr_lines: list[str]) -> list[FieldCheck]:
    """Run every field check. Returns checks; caller rolls up the overall verdict."""
    return [
        _fuzzy_check("brand", "Brand name", app.brand_name, ocr_lines),
        _fuzzy_check("class_type", "Class / type designation", app.class_type, ocr_lines),
        _check_alcohol(app, ocr_lines),
        _check_net_contents(app, ocr_lines),
        _fuzzy_check("bottler_name", "Bottler / producer name", app.bottler_name, ocr_lines),
        # Both sides get address normalization so "Blvd." on the label matches
        # "Boulevard" on the application; the display string stays as-entered.
        _fuzzy_check(
            "address", "Bottler / producer address", app.bottler_address, ocr_lines,
            normalizer=normalize_address,
        ),
        _check_country(app, ocr_lines),
        _check_warning(ocr_lines),
    ]
