import pytest
from sqlalchemy import select

from app.models import NameMismatchLog
from app.services.verify import find_customer, lookup_orders, name_matches


def test_name_matches_is_byte_exact():
    assert name_matches("Mehta Foods", "Mehta Foods")
    assert not name_matches("Mehta Foods", "Mehta Foods ")
    assert not name_matches("Mehta Foods", "mehta foods")
    assert not name_matches("Mehta Foods", "Mehta Foods")
    assert not name_matches(None, "x")


@pytest.mark.asyncio
async def test_lookup_paths(db, clean_sessions):
    c = await find_customer(db, "919876543210")  # Mehta Foods
    assert c is not None
    r = await lookup_orders(db, c, so_no="45240")
    assert r.kind == "ok" and len(r.rows) == 3
    r = await lookup_orders(db, c, po_no="PO-8801")
    assert r.kind == "ok" and r.so_no == "45240"
    r = await lookup_orders(db, c, so_no="99999")
    assert r.kind == "not_found"
    # another customer's SO -> mismatch + logged
    r = await lookup_orders(db, c, so_no="45231")
    assert r.kind == "mismatch"
    logs = (await db.execute(select(NameMismatchLog))).scalars().all()
    assert logs and logs[-1].excel_name == "Mehta Foods" and logs[-1].api_name == "Shree Packaging Pvt Ltd"


@pytest.mark.asyncio
async def test_trailing_space_and_case_are_mismatches(db, clean_sessions):
    patel = await find_customer(db, "919925001122")
    r = await lookup_orders(db, patel, so_no="45260")
    assert r.kind == "mismatch"
    sunrise = await find_customer(db, "919033445566")
    r = await lookup_orders(db, sunrise, so_no="45270")
    assert r.kind == "mismatch"
    assert await find_customer(db, "910000000000") is None
