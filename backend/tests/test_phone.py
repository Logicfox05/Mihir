import pytest

from app.utils.phone import normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9167861236", "919167861236"),
        ("+91 91678-61236", "919167861236"),
        ("09167861236", "919167861236"),
        ("91 9925001122", "919925001122"),
        ("+919712345678", "919712345678"),
        (9167861236.0, "919167861236"),
        (9167861236, "919167861236"),
        ("(091) 67861236", "919167861236"),
    ],
)
def test_ok(raw, expected):
    r = normalize_phone(raw)
    assert r.ok and r.phone == expected


@pytest.mark.parametrize("raw", ["98765", "", None, "abc", "1234567890123", "8812345678901", "+44 20 7946 0958"])
def test_reject(raw):
    r = normalize_phone(raw)
    assert not r.ok and r.phone is None and r.reason
