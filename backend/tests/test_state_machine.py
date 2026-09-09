"""Conversation flows through the full processor with the mocked WATI client.

  first message -> greeting + language buttons -> main menu -> Order status -> SO -> item -> Real Status
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import MessageLog, Session, utcnow
from app.services.wati import wati
from tests.flow import ANAND, GUJ, LANG_BUTTONS, MEHTA, MENU_BUTTONS, PATEL, ROYAL, SHREE, UNKNOWN, open_menu, say, send, step_of, tap, titles

COMPANY = "Gujarat Printpack Publication Private Limited"


# ---------------- first contact ----------------
@pytest.mark.asyncio
async def test_first_message_gets_greeting_then_language_buttons(clean_sessions):
    r = await send(SHREE, "hi")
    assert r.replies and len(r.replies) == 2
    assert r.replies[0].startswith("Hello, thank you for contacting " + COMPANY)
    assert "choose your language" in r.replies[1] and "भाषा" in r.replies[1] and "ભાષા" in r.replies[1]
    assert r.outcome == "ask_language" and titles(r) == LANG_BUTTONS and await step_of(SHREE) == "LANG"


@pytest.mark.asyncio
async def test_anything_first_gets_the_greeting_even_a_code(clean_sessions):
    r = await send(SHREE, "45231")
    assert r.outcome == "ask_language" and len(r.replies) == 2
    # not a language answer -> asked again, nothing else happens
    r = await send(SHREE, "45231")
    assert r.outcome == "ask_language" and len(r.replies) == 1 and await step_of(SHREE) == "LANG"
    # typed language works as well as the button
    r = await send(SHREE, "english")
    assert r.outcome == "menu" and r.reply_text == "Hello Shree Packaging Pvt Ltd, how can we help you today?"
    assert titles(r) == MENU_BUTTONS["en"] and await step_of(SHREE) == "MENU"


@pytest.mark.asyncio
async def test_language_choice_sets_menu_language(clean_sessions):
    r = await open_menu(MEHTA, "हिंदी")
    assert r.reply_text.startswith("नमस्ते Mehta Foods") and titles(r) == MENU_BUTTONS["hi"]
    r = await open_menu(GUJ, "ગુજરાતી")
    assert r.reply_text.startswith("નમસ્તે Gujarat Polymers") and titles(r) == MENU_BUTTONS["gu"]


# ---------------- menu ----------------
@pytest.mark.asyncio
async def test_order_status_buttons_then_result(clean_sessions):
    await open_menu(SHREE)
    r = await tap(SHREE, "Order status")
    assert r.outcome == "ask_so" and r.options["kind"] == "buttons" and titles(r) == ["SO 45232", "SO 45231"]
    assert await step_of(SHREE) == "AWAIT_SO"
    r = await tap(SHREE, "SO 45231")
    assert r.outcome == "status_delivered" and await step_of(SHREE) == "DONE"
    assert r.reply_text.startswith("Hello Shree Packaging Pvt Ltd,\n\nOrder: SO 45231\nReal Status: In Production")
    assert r.reply_text.endswith("Thank you for contacting " + COMPANY + ".")
    assert titles(r) == ["Check another SO", "Main menu", "Done"]
    # DONE accepts another SO directly, typed
    r = await send(SHREE, "SO 45232")
    assert "Dispatched" in r.reply_text
    # "Check another SO" re-opens the order buttons
    r = await tap(SHREE, "Check another SO")
    assert r.outcome == "ask_so" and titles(r) == ["SO 45232", "SO 45231"]
    # "Main menu" goes back to the menu
    r = await tap(SHREE, "Main menu")
    assert r.outcome == "menu" and titles(r) == MENU_BUTTONS["en"]


@pytest.mark.asyncio
async def test_so_menu_style_list_setting(clean_sessions, monkeypatch):
    monkeypatch.setattr(get_settings(), "so_menu_style", "list")
    await open_menu(SHREE)
    r = await tap(SHREE, "Order status")
    assert r.options["kind"] == "list" and titles(r) == ["SO 45232", "SO 45231"] and r.options["button_text"] == "Select SO"
    r = await tap(SHREE, "SO 45231")
    assert r.outcome == "status_delivered"


@pytest.mark.asyncio
async def test_more_than_three_orders_become_a_list(clean_sessions):
    from types import SimpleNamespace

    from app.services import menus

    rows = [SimpleNamespace(so_no=str(45200 + i), fg_item_code="FG-1", po_no=None) for i in range(4)]
    o = menus.so_options(rows, "en", "auto")
    assert o.kind == "list" and len(o.items) == 4
    assert menus.so_options(rows[:3], "en", "auto").kind == "buttons"


@pytest.mark.asyncio
async def test_multi_item_so_offers_item_buttons(clean_sessions):
    await open_menu(MEHTA)
    r = await tap(MEHTA, "Order status")
    assert titles(r) == ["SO 45240"]
    r = await tap(MEHTA, "SO 45240")
    assert r.outcome == "ask_fg" and "SO 45240 has 3 items" in r.reply_text and await step_of(MEHTA) == "AWAIT_FG"
    assert r.options["kind"] == "buttons" and titles(r) == ["FG-2001", "FG-2002", "FG-2003"]
    r = await tap(MEHTA, "FG-2002")
    assert r.outcome == "status_delivered" and "Order: SO 45240, item FG-2002\nReal Status: Printing" in r.reply_text
    assert await step_of(MEHTA) == "DONE"


@pytest.mark.asyncio
async def test_typed_so_and_fg_still_work(clean_sessions):
    await open_menu(MEHTA)
    r = await say(MEHTA, "SO no 45240")
    assert "3 items" in r and await step_of(MEHTA) == "AWAIT_FG"
    r = await say(MEHTA, "2003")  # bare number while an item is expected = item code
    assert "Awaiting Material" in r
    await open_menu(GUJ)
    assert "Slitting" in await say(GUJ, "SO 45250 FG-3002")


@pytest.mark.asyncio
async def test_wrong_fg_twice_then_apology(clean_sessions):
    await open_menu(GUJ)
    await say(GUJ, "45250")
    assert await step_of(GUJ) == "AWAIT_FG"
    r = await send(GUJ, "FG-9999")
    assert "FG-9999 is not in SO 45250" in r.reply_text and titles(r) == ["FG-3001", "FG-3002"] and await step_of(GUJ) == "AWAIT_FG"
    r = await send(GUJ, "FG-8888")
    assert r.outcome == "not_found" and "Sorry Gujarat Polymers" in r.reply_text and await step_of(GUJ) == "AWAIT_SO"
    assert titles(r) == ["Show my orders", "Main menu"]
    r = await tap(GUJ, "Show my orders")
    assert r.outcome == "ask_so" and titles(r) == ["SO 45250"]


@pytest.mark.asyncio
async def test_po_lookup(clean_sessions):
    await open_menu(ROYAL)
    r = await say(ROYAL, "PO PO-7777")
    assert "Delivered" in r and "45280" in r


@pytest.mark.asyncio
async def test_no_orders_for_this_customer(clean_sessions):
    await open_menu(ANAND)
    r = await tap(ANAND, "Order status")
    assert r.outcome == "ask_so" and r.reply_text.startswith("Hello Anand Dairy Products, we could not find any orders")
    assert titles(r) == ["Main menu", "Contact us"]
    r = await say(ANAND, "12345")
    assert "could not find that SO number" in r


@pytest.mark.asyncio
async def test_contact_us_and_change_language(clean_sessions):
    await open_menu(SHREE)
    r = await tap(SHREE, "Contact us")
    assert r.outcome == "contact" and "support@test" in r.reply_text and titles(r) == ["Order status", "Main menu"]
    assert await step_of(SHREE) == "MENU"
    r = await tap(SHREE, "Change language")
    assert r.outcome == "ask_language" and titles(r) == LANG_BUTTONS and await step_of(SHREE) == "LANG"
    r = await tap(SHREE, "ગુજરાતી")
    assert r.outcome == "menu" and r.reply_text.startswith("નમસ્તે Shree Packaging Pvt Ltd") and titles(r) == MENU_BUTTONS["gu"]
    r = await tap(SHREE, "ઓર્ડર સ્ટેટસ")
    assert r.outcome == "ask_so" and "SO નંબર" in r.reply_text


@pytest.mark.asyncio
async def test_chosen_language_sticks_whatever_the_customer_types(clean_sessions):
    await open_menu(SHREE, "हिंदी")
    r = await say(SHREE, "check status of SO 45231")  # English text, Hindi stays
    assert r.startswith("नमस्ते Shree Packaging Pvt Ltd") and "In Production" in r and "Real Status" in r
    r = await send(SHREE, "menu")
    assert titles(r) == MENU_BUTTONS["hi"]


@pytest.mark.asyncio
async def test_done_ends_the_window_and_next_message_greets_again(clean_sessions):
    await open_menu(SHREE)
    await say(SHREE, "45231")
    r = await tap(SHREE, "Done")
    assert r.outcome == "bye" and r.reply_text.startswith("Thank you Shree Packaging Pvt Ltd") and await step_of(SHREE) == "START"
    r = await send(SHREE, "hello")
    assert r.outcome == "ask_language" and len(r.replies) == 2


@pytest.mark.asyncio
async def test_idle_timeout_starts_a_new_window(clean_sessions):
    await open_menu(SHREE)
    async with session_scope() as db:
        s = await db.get(Session, SHREE)
        s.updated_at = utcnow() - timedelta(minutes=get_settings().session_timeout_min + 1)
    r = await send(SHREE, "45231")
    assert r.outcome == "ask_language" and len(r.replies) == 2 and await step_of(SHREE) == "LANG"


# ---------------- verification ----------------
@pytest.mark.asyncio
async def test_mismatch_gives_verify_failed_and_restarts(clean_sessions):
    await open_menu(ANAND)
    r = await say(ANAND, "45231")  # exists but belongs to Shree -> mismatch -> verify failed (trilingual)
    assert "could not verify" in r and "क्षमा" in r and "માફ" in r and await step_of(ANAND) == "START"


@pytest.mark.asyncio
async def test_unknown_phone_verify_failed(clean_sessions):
    r = await say(UNKNOWN, "hi")
    assert "could not verify" in r and "support@test" in r


@pytest.mark.asyncio
async def test_trailing_space_name_is_a_mismatch(clean_sessions):
    await open_menu(PATEL)
    r = await say(PATEL, "45260")
    assert "could not verify" in r


# ---------------- voice ----------------
@pytest.mark.asyncio
async def test_voice_confirm_yes_and_no(clean_sessions):
    await open_menu(SHREE)
    r = await send(SHREE, audio=True)  # fixture transcript: "my SO number is 45231"
    assert "Did you mean SO number 45231" in r.reply_text and titles(r) == ["Yes", "No"] and await step_of(SHREE) == "CONFIRM"
    r = await tap(SHREE, "No")
    assert r.outcome == "ask_so" and titles(r) == ["SO 45232", "SO 45231"] and await step_of(SHREE) == "AWAIT_SO"
    await send(SHREE, audio=True)
    r = await tap(SHREE, "Yes")
    assert "In Production" in r.reply_text and await step_of(SHREE) == "DONE"


@pytest.mark.asyncio
async def test_voice_confirm_replaced_by_typed_number(clean_sessions):
    await open_menu(SHREE)
    r = await say(SHREE, audio=True)
    assert "45231" in r
    r = await say(SHREE, "45232")
    assert "Dispatched" in r


# ---------------- logging ----------------
@pytest.mark.asyncio
async def test_outgoing_logged_and_outbox(clean_sessions):
    n0 = len(wati.outbox)
    r = await send(SHREE, "hi")
    assert len(wati.outbox) == n0 + 2 and wati.outbox[-1]["phone"] == SHREE and wati.outbox[-1]["kind"] == "buttons"
    await tap(SHREE, "English")
    await say(SHREE, "45231")
    async with session_scope() as db:
        rows = (await db.execute(select(MessageLog).where(MessageLog.direction == "out"))).scalars().all()
    assert [x.outcome for x in rows] == ["welcome", "ask_language", "menu", "status_delivered"]
    assert rows[-1].outcome == "status_delivered" and rows[-1].step_after == "DONE"
