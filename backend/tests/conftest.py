from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

_TEST_DB = BACKEND / "test_order_bot.db"
# Run against MySQL with:  $env:TEST_DATABASE_URL = "mysql+aiomysql://root:root@localhost:3306/order_bot_test"
_DB_URL = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{_TEST_DB.as_posix()}"

# The tests always use the 10 built-in dummy customers, written fresh here, so editing
# fixtures/customers_dummy.xlsx (e.g. to put your own WhatsApp number in for a live test) never
# breaks the test suite.
from scripts.make_fixtures import write_customers  # noqa: E402

CUSTOMERS_XLSX = write_customers(BACKEND / "tests" / "_generated" / "customers_dummy.xlsx")
os.environ.update(
    {
        "APP_MODE": "dev",
        "DATABASE_URL": _DB_URL,
        "WATI_TOKEN": "",
        "WATI_DRY_RUN": "",
        "GROQ_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ADMIN_KEY": "test-admin",
        "WATI_WEBHOOK_TOKEN": "test-hook",
        "SUPPORT_CONTACT": "support@test",
        "ORDERS_SOURCE": "file",
        "ORDERS_FILE_PATH": "fixtures/orders_dummy.json",
        "CUSTOMERS_FILE_PATH": CUSTOMERS_XLSX.relative_to(BACKEND).as_posix(),
        "FG_MAX_ATTEMPTS": "2",
        "RATE_LIMIT_MSGS": "1000",
    }
)

from app.config import get_settings  # noqa: E402
from app.db import dispose_db, init_db, session_scope  # noqa: E402
from app.jobs import customer_sync, order_refresh  # noqa: E402

get_settings.cache_clear()


def pytest_collection_modifyitems(items):
    """Run every async test on ONE session-scoped loop: the aiomysql pool binds connections to the
    loop that created them, so per-test loops would fail with 'attached to a different loop'."""
    for item in items:
        if asyncio.iscoroutinefunction(getattr(item, "obj", None)):
            # append=False: must come BEFORE the marker auto-mode already added, or it is ignored
            item.add_marker(pytest.mark.asyncio(loop_scope="session"), append=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _db():
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    if not _DB_URL.startswith("sqlite"):
        # fresh schema on the external test database
        from app.db import Base, get_engine

        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    c = await customer_sync.run()
    assert c.ok, c.error
    o = await order_refresh.run()
    assert o.ok, o.error
    from app.services import templates

    await templates.load_from_db()
    yield
    await dispose_db()
    try:
        _TEST_DB.unlink()
    except OSError:
        pass


@pytest_asyncio.fixture
async def db():
    async with session_scope() as s:
        yield s


@pytest_asyncio.fixture
async def clean_sessions():
    from sqlalchemy import delete

    from app.models import InboundQueue, MessageLog, NameMismatchLog, Session

    async with session_scope() as s:
        await s.execute(delete(Session))
        await s.execute(delete(MessageLog))
        await s.execute(delete(InboundQueue))
        await s.execute(delete(NameMismatchLog))
    yield
