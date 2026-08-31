"""Unit tests for the Government Warning strict checker."""
from app.engine.warning_text import CANONICAL_WARNING, check_warning


def by_field(checks, field):
    return next(c for c in checks if c.field == field)


def test_exact_warning_passes():
    check = check_warning(CANONICAL_WARNING)
    assert check.exact
    assert check.header_state == "exact"
    assert not check.diffs and not check.artifacts


def test_lowercase_header_is_wrong_case():
    text = "Government Warning:" + CANONICAL_WARNING[len("GOVERNMENT WARNING:"):]
    check = check_warning(text)
    assert check.header_state == "wrong_case"
    assert not check.header_ok


def test_header_ocr_case_noise_tolerated():
    # OCR often mis-cases one letter of bold all-caps text.
    check = check_warning(CANONICAL_WARNING.replace("GOVERNMENT", "GoVERNMENT", 1))
    assert check.header_state == "ocr_case_noise"
    assert check.header_ok


def test_merged_words_are_absorbed():
    # OCR merging adjacent words must not create diffs.
    words = CANONICAL_WARNING.replace("According to the", "Accordingtothe")
    words = words.replace("health problems", "healthproblems")
    check = check_warning(words)
    assert check.exact


def test_single_char_misread_is_artifact():
    check = check_warning(CANONICAL_WARNING.replace("General", "Genral"))
    assert not check.diffs
    assert len(check.artifacts) == 1
    assert check.ocr_noise_only  # -> REVIEW verdict in the engine


def test_missing_word_is_hard_diff():
    check = check_warning(CANONICAL_WARNING.replace(" operate machinery,", ""))
    assert check.diffs
    assert not check.ocr_noise_only


def test_substituted_word_is_hard_diff():
    check = check_warning(
        CANONICAL_WARNING.replace("may cause health problems", "may cause serious health problems")
    )
    assert any("SERIOUS" in d for d in check.diffs)
    assert not check.ocr_noise_only


def test_truncated_warning_reports_missing_tail():
    cut = CANONICAL_WARNING[: CANONICAL_WARNING.rindex("operate") + len("operate")]
    check = check_warning(cut)
    assert any("missing" in d for d in check.diffs)


def test_missing_header_entirely():
    body = CANONICAL_WARNING.replace("GOVERNMENT WARNING: ", "")
    check = check_warning(body)
    assert check.header_state == "missing" or check.diffs  # either way: not ok
    assert not (check.header_ok and check.exact)


def test_digits_ignored_everywhere():
    # "(1)"/"(2)" markers are unreliable in OCR; their absence is not a diff.
    assert check_warning(CANONICAL_WARNING.replace("(1)", "").replace("(2)", "")).exact
