import pytest

from provguard.core.extraction import ExtractionError, validate_extraction
from provguard.core.plan import FieldSpec

SCHEMA = {
    "iban": FieldSpec(type="str", pattern="^[A-Z]{2}[0-9A-Z]{4,32}$"),
    "total": FieldSpec(type="float", minimum=0, maximum=1000),
    "n": FieldSpec(type="int", enum=[1, 2]),
    "ok": FieldSpec(type="bool"),
    "kind": FieldSpec(type="str", enum=["bill", "notice"]),
}
GOOD = {"iban": "UK12345678901234567890", "total": 98, "n": 2.0, "ok": True, "kind": "bill"}


def test_valid_extraction_coerces_numbers():
    out = validate_extraction(SCHEMA, GOOD)
    assert out["total"] == 98.0 and isinstance(out["total"], float) and out["n"] == 2


@pytest.mark.parametrize(
    "bad",
    [
        "not an object",
        {**GOOD, "extra": 1},
        {k: v for k, v in GOOD.items() if k != "n"},
        {**GOOD, "iban": "nope"},
        {**GOOD, "iban": 5},
        {**GOOD, "total": -1},
        {**GOOD, "total": 1001},
        {**GOOD, "total": "98"},
        {**GOOD, "total": True},
        {**GOOD, "n": 2.5},
        {**GOOD, "n": 3},
        {**GOOD, "ok": "yes"},
        {**GOOD, "kind": "email"},
    ],
)
def test_invalid_extraction(bad):
    with pytest.raises(ExtractionError):
        validate_extraction(SCHEMA, bad)


def test_optional_fields_accept_null_or_absence_and_required_still_fail():
    from provguard.core.extraction import ExtractionError, validate_extraction
    from provguard.core.plan import FieldSpec

    schema = {"iban": FieldSpec(type="str"), "note": FieldSpec(type="str", optional=True)}
    assert validate_extraction(schema, {"iban": "DE1", "note": None}) == {"iban": "DE1", "note": None}
    assert validate_extraction(schema, {"iban": "DE1"}) == {"iban": "DE1", "note": None}
    assert validate_extraction(schema, {"iban": "DE1", "note": "x"})["note"] == "x"
    import pytest

    with pytest.raises(ExtractionError, match="expected str"):
        validate_extraction(schema, {"iban": None, "note": "x"})
    with pytest.raises(ExtractionError, match="expected str"):
        validate_extraction(schema, {"iban": "DE1", "note": 3})
