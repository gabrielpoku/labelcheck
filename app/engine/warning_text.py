"""Strict verification of the mandatory Government Health Warning (27 CFR 16.21).

Rules:
- The statement must match word-for-word.
- "GOVERNMENT WARNING:" must appear in all capital letters, and in bold. Bold
  is not recoverable from OCR, so it is flagged for the reviewer rather than
  silently assumed.

OCR reality on real labels:
- Adjacent words are frequently merged into one token ("ACCORDINGTOTHE").
- Characters are occasionally misread ("Governrnent", "Genral").

So the comparison walks the found tokens against the canonical word sequence,
absorbing exact word merges and single-character misreads as *OCR artifacts*,
and reports anything else (missing words, extra words, substituted words) as
a hard difference. Artifacts alone surface as REVIEW (a human should glance at
the image); any real difference is a MISMATCH.

Header case: OCR sometimes mis-cases a letter or two of bold all-caps text, so
a header that is >=85% uppercase letters is accepted as all-caps. A genuinely
mixed-case header ("Government Warning:") is a MISMATCH.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

_HEADER = re.compile(r"GOVERNMENT\s+WARNING\s*:?", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[^A-Z0-9]+")
_DIGIT = re.compile(r"^\d+$")

# How many single-character OCR artifacts we will soften into a REVIEW.
_MAX_ARTIFACTS = 3
# Minimum share of uppercase letters for the header to count as all-caps.
_HEADER_CAPS_RATIO = 0.85


def _words(text: str) -> list[str]:
    # Pure digits ("(1)") are unreliable in OCR and are not words; drop them.
    return [w for w in _WORD_SPLIT.split(text.upper()) if w and not _DIGIT.match(w)]


_CANONICAL_WORDS = _words(CANONICAL_WARNING)


@dataclass
class WarningCheck:
    header_state: str                 # exact | ocr_case_noise | wrong_case | missing
    header_found: str | None
    diffs: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    @property
    def header_ok(self) -> bool:
        return self.header_state in {"exact", "ocr_case_noise"}

    @property
    def exact(self) -> bool:
        return not self.diffs and not self.artifacts

    @property
    def ocr_noise_only(self) -> bool:
        return not self.diffs and 0 < len(self.artifacts) <= _MAX_ARTIFACTS


def _check_header(found_text: str) -> tuple[str, str | None]:
    match = _HEADER.search(found_text)
    if match:
        header = match.group(0)
        letters = [c for c in header.upper() if c.isalpha()]
        lower = sum(1 for c in header if c.islower())
        if lower == 0:
            return "exact", header
        if letters and lower / len(letters) <= (1 - _HEADER_CAPS_RATIO):
            return "ocr_case_noise", header
        return "wrong_case", header

    # No clean regex hit. OCR may have merged or misread the header itself
    # ("GOOVERNMENTWARNING:"). Accept a fuzzy match at the start of the region.
    from rapidfuzz import fuzz

    head = found_text[:40].upper().replace(" ", "")
    if fuzz.partial_ratio("GOVERNMENTWARNING", head) >= 85:
        snippet = found_text.split(":", 1)[0][:30]
        return "ocr_case_noise", snippet
    return "missing", None


def check_warning(found_text: str) -> WarningCheck:
    """Compare the warning statement found on the label against the canonical text."""
    header_state, header_found = _check_header(found_text)
    check = WarningCheck(header_state=header_state, header_found=header_found)

    canon = _CANONICAL_WORDS
    found = _words(found_text)
    ci = 0

    for fw in found:
        cur = canon[ci] if ci < len(canon) else None

        # 1. Exact word.
        if cur is not None and fw == cur:
            ci += 1
            continue

        # 2. Single-character misread of the expected word -> OCR artifact.
        if cur is not None and len(cur) >= 5 and Levenshtein.distance(fw, cur) <= 1:
            check.artifacts.append(f'"{cur}" appears as "{fw}"')
            ci += 1
            continue

        # 3. Merged words: token equals 2-4 consecutive canonical words
        #    (allowing one misread character inside the merge).
        merged = False
        for k in (2, 3, 4):
            if ci + k > len(canon):
                break
            joined = "".join(canon[ci:ci + k])
            dist = Levenshtein.distance(fw, joined)
            if dist <= 1 and len(joined) - len(fw) <= 2:
                if dist > 0:
                    check.artifacts.append(f'"{joined}" appears as "{fw}"')
                ci += k
                merged = True
                break
        if merged:
            continue

        # 4. A canonical word was omitted; the token matches the next one(s).
        if cur is not None:
            skip = next(
                (s for s in (1, 2) if ci + s < len(canon) and fw == canon[ci + s]),
                None,
            )
            if skip is not None:
                check.diffs.append(f'missing word(s): {" ".join(canon[ci:ci + skip])}')
                ci += skip + 1
                continue

        # 5. Genuine word-level difference (substitution, or extra word).
        if cur is not None:
            if Levenshtein.distance(fw, cur) <= 4:
                check.diffs.append(f'"{cur}" appears as "{fw}"')
            else:
                check.diffs.append(f'unexpected word "{fw}" (expected "{cur}")')
            ci += 1
        else:
            check.diffs.append(f'unexpected word(s): "{fw}"')

    if ci < len(canon):
        check.diffs.append(f'missing word(s): {" ".join(canon[ci:])}')

    return check
