from pipeline.schema import Extraction, FieldValue
from pipeline.validate import validate
from tests.conftest import good_values


def statuses(findings):
    return {f.rule: f.status for f in findings}


def test_consistent_receipt_passes(good_extraction, today):
    s = statuses(validate(good_extraction, today=today))
    assert s["required_fields_present"] == "pass"
    assert s["sum_items_equals_subtotal"] == "pass"
    assert s["subtotal_plus_tax_equals_total"] == "pass"
    assert s["line_qty_times_price"] == "pass"
    assert s["issue_date_valid"] == "pass"
    assert s["tax_rate_matches_config"] == "pass"  # 11%


def test_total_mismatch_is_warning(good_extraction, today):
    good_extraction.total = FieldValue(value=999999.0)
    assert statuses(validate(good_extraction, today=today))["subtotal_plus_tax_equals_total"] == "warning"


def test_item_sum_mismatch(good_extraction, today):
    good_extraction.line_items[0].amount = 1.0
    s = statuses(validate(good_extraction, today=today))
    assert s["sum_items_equals_subtotal"] == "warning"
    assert s["line_qty_times_price"] == "warning"


def test_future_date_fails(good_extraction, today):
    good_extraction.issue_date = FieldValue(value="2027-01-01")
    assert statuses(validate(good_extraction, today=today))["issue_date_valid"] == "fail"


def test_missing_required_fields_fail(today):
    s = statuses(validate(Extraction(), today=today))
    assert s["required_fields_present"] == "fail"
    assert s["total_positive"] == "fail"
    assert s["issue_date_valid"] == "fail"


def test_bad_tax_id_and_rate(today):
    v = good_values()
    v["vendor_tax_id"] = "12345"
    v["tax_amount"] = 50000.0
    v["total"] = 294000.0
    s = statuses(validate(Extraction.from_values(v), today=today))
    assert s["vendor_tax_id_format"] == "warning"
    assert s["tax_rate_matches_config"] == "warning"


def test_receipt_without_subtotal_compares_items_to_total(today):
    v = good_values()
    v.update(subtotal=None, tax_amount=None, total=244000.0)
    s = statuses(validate(Extraction.from_values(v), today=today))
    assert s["sum_items_equals_subtotal"] == "pass"
    assert s["subtotal_plus_tax_equals_total"] == "skipped"
