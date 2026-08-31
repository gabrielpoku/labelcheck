"""Unit tests for the field-by-field verification engine (no OCR involved).

OCR lines here are realistic transcripts including common OCR quirks
(merged words, dropped spaces after digits, mis-cased bold text).
"""
from app.engine.models import ApplicationData, Verdict
from app.engine.verify import verify_label

APP = ApplicationData(
    application_id="T-1",
    brand_name="Stone's Throw",
    **{"class/type": "Kentucky Straight Bourbon Whiskey"},
    alcohol_pct=45.0,
    net_contents_ml=750,
    bottler_name="Old Tom Distillery Co.",
    bottler_address="123 Barrel Lane, Frankfort, KY 40601",
)

# Realistic OCR transcript of a fully compliant label (quirks included).
GOOD_LINES = [
    "STONE'STHROW",                                # merged brand, upper case
    "Kentucky Straight Bourbon Whiskey",
    "45% ALC.NOL. (90 PROOF)",
    "750 mL",
    "Bottled by Old Tom Distillery Co.",
    "123 Barrel Lane, Frankfort, KY40601",         # lost space after digits
    "GOVERNMENT WARNING: (1) According to the Surgeon",
    "General, women should not drink alcoholic beverages",
    "during pregnancy because of the risk of birth defects. (2)",
    "Consumption of alcoholic beverages impairs your ability",
    "to drive a car or operate machinery, and may cause",
    "health problems.",
]


def by_field(checks, field):
    return next(c for c in checks if c.field == field)


def test_compliant_label_all_match():
    checks = verify_label(APP, GOOD_LINES)
    assert all(c.verdict is Verdict.MATCH for c in checks if c.field != "country_of_origin")
    assert by_field(checks, "country_of_origin").verdict is Verdict.NOT_APPLICABLE


def test_case_difference_on_brand_is_not_an_error():
    """Dave Morrison: 'STONE'S THROW' vs 'Stone's Throw' is obviously the same brand."""
    lines = ["stone's throw"] + GOOD_LINES[1:]
    checks = verify_label(APP, lines)
    assert by_field(checks, "brand").verdict is Verdict.MATCH


def test_wrong_brand_is_flagged():
    lines = ["Copper Fox"] + GOOD_LINES[1:]
    checks = verify_label(APP, lines)
    # Brand absent from the label entirely -> NOT_FOUND (a failing verdict:
    # displayed as "NOT ON LABEL" in the UI).
    assert by_field(checks, "brand").verdict is Verdict.NOT_FOUND


def test_near_miss_brand_goes_to_review():
    lines = ["Stone's Throw Vineyard Co"] + GOOD_LINES[1:]
    checks = verify_label(APP, lines)
    brand = by_field(checks, "brand")
    assert brand.verdict in (Verdict.MATCH, Verdict.REVIEW)  # never silently mismatch


def test_wrong_abv_is_mismatch():
    lines = GOOD_LINES[:2] + ["43% ALC./VOL. (86 PROOF)"] + GOOD_LINES[3:]
    checks = verify_label(APP, lines)
    assert by_field(checks, "alcohol_content").verdict is Verdict.MISMATCH


def test_proof_only_label_derives_abv():
    lines = GOOD_LINES[:2] + ["90 PROOF"] + GOOD_LINES[3:]
    checks = verify_label(APP, lines)
    assert by_field(checks, "alcohol_content").verdict is Verdict.MATCH


def test_missing_abv_statement_is_not_found():
    lines = GOOD_LINES[:2] + GOOD_LINES[3:]
    checks = verify_label(APP, lines)
    assert by_field(checks, "alcohol_content").verdict is Verdict.NOT_FOUND


def test_wrong_net_contents_is_mismatch():
    lines = GOOD_LINES[:3] + ["500 mL"] + GOOD_LINES[4:]
    checks = verify_label(APP, lines)
    assert by_field(checks, "net_contents").verdict is Verdict.MISMATCH


def test_net_contents_unit_conversion():
    lines = GOOD_LINES[:3] + ["1.75 L"] + GOOD_LINES[4:]
    checks = verify_label(ApplicationData(**{**APP.model_dump(), "net_contents_ml": 1750}), lines)
    assert by_field(checks, "net_contents").verdict is Verdict.MATCH


def test_abbreviated_address_matches():
    lines = ["123 Barrel Rd., Frankfort, KY 40601"] + GOOD_LINES[1:]
    checks = verify_label(
        ApplicationData(**{**APP.model_dump(), "bottler_address": "123 Barrel Road, Frankfort, KY 40601"}),
        lines,
    )
    assert by_field(checks, "address").verdict is Verdict.MATCH


def test_import_country_found_via_product_of():
    app = ApplicationData(
        **{**APP.model_dump(), "is_import": True, "country_of_origin": "France"}
    )
    lines = ["Product of France"] + GOOD_LINES
    checks = verify_label(app, lines)
    assert by_field(checks, "country_of_origin").verdict is Verdict.MATCH


def test_import_country_missing_is_flagged():
    app = ApplicationData(
        **{**APP.model_dump(), "is_import": True, "country_of_origin": "France"}
    )
    checks = verify_label(app, GOOD_LINES)
    assert by_field(checks, "country_of_origin").verdict is Verdict.NOT_FOUND


def test_warning_ocr_noise_gives_review():
    lines = GOOD_LINES[:6] + [
        "GOVERNMENT WARNING: (1) According to the Surgeon",
        "Genral, women should not drink alcoholic beverages",
    ] + GOOD_LINES[8:]
    checks = verify_label(APP, lines)
    assert by_field(checks, "government_warning").verdict is Verdict.REVIEW


def test_warning_word_change_gives_mismatch():
    lines = GOOD_LINES[:11] + [
        "to drive a car or operate machinery, and may cause",
        "serious health problems.",
    ]
    checks = verify_label(APP, lines)
    assert by_field(checks, "government_warning").verdict is Verdict.MISMATCH


def test_missing_warning_is_not_found():
    checks = verify_label(APP, GOOD_LINES[:6])
    assert by_field(checks, "government_warning").verdict is Verdict.NOT_FOUND


def test_empty_ocr_marks_fields_missing():
    checks = verify_label(APP, [])
    assert by_field(checks, "brand").verdict is Verdict.NOT_FOUND
    assert by_field(checks, "government_warning").verdict is Verdict.NOT_FOUND
