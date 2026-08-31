"""Unit tests for text normalization."""
from app.engine.normalize import normalize_address, normalize_fold, normalize_ws


def test_fold_case_and_punctuation():
    assert normalize_fold("STONE'S THROW") == normalize_fold("stone's throw") == "stone s throw"
    assert normalize_fold("  Old   Tom   Distillery Co. ") == "old tom distillery co"


def test_fold_handles_unicode():
    # Accents fold to their base letters so diacritics never block a match.
    assert normalize_fold("Château Rouge") == "chateau rouge"
    assert normalize_fold("ＦＵＬＬＷＩＤＴＨ") == "fullwidth"  # NFKC folds width too


def test_ws_preserves_case_and_punctuation():
    assert normalize_ws("  hello   WORLD. ") == "hello WORLD."


def test_address_expands_abbreviations_symmetrically():
    assert normalize_address("500 Harbor Blvd, Newark, NJ") == normalize_address(
        "500 Harbor Boulevard, Newark, NJ"
    )
    assert "road" in normalize_address("7 Mile Rd.")


def test_address_keeps_ambiguous_st_alone():
    # "St" can be Saint or Street, so it must not be forcibly expanded.
    assert "st" in normalize_address("120 St James St").split()
