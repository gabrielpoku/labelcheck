"""Text normalization helpers.

Two levels:
- ``normalize_fold``: case/punctuation preserving only structure. Case differences
  alone (e.g. "STONE'S THROW" vs "Stone's Throw") must NOT be flagged as errors,
  so most comparisons fold case and punctuation away.
- ``normalize_address``: additionally expands common street abbreviations so
  "123 Main St." matches "123 Main Street".
"""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def _strip_accents(text: str) -> str:
    # NFKD decomposes accented letters into base + combining marks; dropping
    # the marks turns "Château" into "Chateau" so diacritics never block a match.
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_fold(text: str) -> str:
    """Casefold, strip accents/punctuation, collapse whitespace."""
    text = _strip_accents(unicodedata.normalize("NFKC", text))
    text = _NON_ALNUM.sub(" ", text.casefold())
    return _WS.sub(" ", text).strip()


def normalize_ws(text: str) -> str:
    """Collapse whitespace only; case and punctuation are preserved."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip()


# Symmetric expansions: both sides are mapped, so "Rd." on the label and
# "Road" on the application both become "road". Ambiguous abbreviations
# (e.g. "St." = Saint/Street) are intentionally left alone; fuzzy matching
# absorbs those.
_ADDRESS_TOKENS = {
    "rd": "road",
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "ste": "suite",
    "ct": "court",
    "dr": "drive",
    "ln": "lane",
    "sq": "square",
    "hwy": "highway",
    "bldg": "building",
}


def normalize_address(text: str) -> str:
    folded = normalize_fold(text)
    return " ".join(_ADDRESS_TOKENS.get(tok, tok) for tok in folded.split())
