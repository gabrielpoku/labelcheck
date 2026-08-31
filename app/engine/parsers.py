"""Parsers that turn free-form OCR text into structured values.

Labels express mandatory quantities in many ways:
- Alcohol:  "45% ALC./VOL.", "45% ALC BY VOL", "90 PROOF", "90\u00b0 PROOF"
- Net contents: "750 mL", "750ML", "1.75 L", "1 LITRE", "50ml", "25.4 FL OZ"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FL_OZ_TO_ML = 29.5735


@dataclass
class ParsedAlcohol:
    abv: float | None = None       # percent alcohol by volume
    proof: float | None = None     # degrees proof (US proof = 2 x ABV)

    @property
    def consistent(self) -> bool:
        return (
            self.abv is None
            or self.proof is None
            or abs(self.abv * 2 - self.proof) <= 0.51
        )


def parse_alcohol(text: str) -> ParsedAlcohol:
    """Extract ABV and proof mentions from a chunk of label text."""
    upper = text.upper()
    abv = proof = None

    # Prefer an explicit "N% ALC/VOL" style statement over a bare percentage.
    abv_match = re.search(
        r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*(?:ALC|ALCOHOL|ABV|VOL|BY\s+VOL)", upper
    )
    if not abv_match:
        abv_match = re.search(r"(?:ALC|ALCOHOL|ABV)[^\d%]{0,12}(\d{1,2}(?:[.,]\d{1,2})?)\s*%", upper)
    if not abv_match:
        # Fall back to any percentage on the line (rare: the only % on a label
        # is almost always the ABV statement).
        abv_match = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", upper)
    if abv_match:
        abv = float(abv_match.group(1).replace(",", "."))

    proof_match = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*(?:\u00b0\s*)?PROOF", upper)
    if proof_match:
        proof = float(proof_match.group(1).replace(",", "."))
        if abv is None:
            abv = proof / 2  # derive ABV when only proof is printed

    return ParsedAlcohol(abv=abv, proof=proof)


def parse_net_contents_ml(text: str) -> float | None:
    """Extract net contents from label text, normalized to milliliters."""
    upper = text.upper()

    ml = re.search(r"(\d{1,4}(?:[.,]\d{1,3})?)\s*(?:MILLILITRES?|MILLILITERS?|ML)\b", upper)
    if ml:
        return float(ml.group(1).replace(",", "."))

    liters = re.search(r"(\d{1,2}(?:[.,]\d{1,3})?)\s*(?:LITRES?|LITERS?|L)\b(?![A-Z])", upper)
    if liters:
        return float(liters.group(1).replace(",", ".")) * 1000

    fl_oz = re.search(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:FL\.?\s*OZ|FLUID\s+OUNCE)", upper)
    if fl_oz:
        return round(float(fl_oz.group(1).replace(",", ".")) * FL_OZ_TO_ML, 1)

    return None

