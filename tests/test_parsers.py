"""Unit tests for the alcohol and net-contents parsers."""
import pytest

from app.engine.parsers import ParsedAlcohol, parse_alcohol, parse_net_contents_ml


@pytest.mark.parametrize("text,abv,proof", [
    ("45% ALC./VOL. (90 PROOF)", 45.0, 90.0),
    ("43% ALC. BY VOL.", 43.0, None),
    ("13.5% ALCOHOL BY VOLUME", 13.5, None),
    ("80 PROOF", 40.0, 80.0),          # ABV derived from proof
    ("45%ALC.VOL.(90PROOF)", 45.0, 90.0),  # OCR merged spaces
    ("40% ALC 80 PROOF", 40.0, 80.0),
    ("Nothing here", None, None),
    ("Distilled at 120 feet", None, None),  # bare number must not parse as %
])
def test_parse_alcohol(text, abv, proof):
    got = parse_alcohol(text)
    assert got.abv == abv
    assert got.proof == proof


def test_alcohol_consistency_flag():
    assert ParsedAlcohol(abv=45, proof=90).consistent
    assert not ParsedAlcohol(abv=45, proof=80).consistent


@pytest.mark.parametrize("text,ml", [
    ("750 mL", 750.0),
    ("750ML", 750.0),
    ("1.75 L", 1750.0),
    ("1 LITRE", 1000.0),
    ("50ml", 50.0),
    ("750 mL (25.4 FL OZ)", 750.0),
    ("25.4 FL OZ", 750.1),
    ("NET CONTENTS 750 mL", 750.0),
    ("no size printed", None),
])
def test_parse_net_contents(text, ml):
    got = parse_net_contents_ml(text)
    if ml is None:
        assert got is None
    else:
        assert got == pytest.approx(ml, rel=0.01)
