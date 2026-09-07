"""Real-HTTP behaviour of the WATI client (mock mode OFF, WATI mocked at the HTTP layer with respx)."""
import json

import pytest
import respx
from httpx import Response

from app.config import get_settings
from app.services import menus
from app.services.wati import WatiClient

BASE = "https://live-mt-server.wati.io/tenant123"


@pytest.fixture
def live_wati(monkeypatch):
    monkeypatch.setenv("WATI_BASE_URL", BASE)
    monkeypatch.setenv("WATI_TOKEN", "tok123")
    monkeypatch.setenv("WATI_DRY_RUN", "false")
    get_settings.cache_clear()
    yield WatiClient()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_list_uses_query_param_and_documented_body(live_wati):
    opts = menus.Options(kind="list", items=[menus.Option("SO 45240", "3 items"), menus.Option("SO 45231", "1 item")], button_text="Select SO", section_title="Your orders")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{BASE}/api/v1/sendInteractiveListMessage").mock(return_value=Response(200, json={"ok": True}))
        await live_wati.send_list("919876543210", "Pick", opts)
    req = route.calls.last.request
    assert req.url.params["whatsappNumber"] == "919876543210"
    assert req.headers["Authorization"] == "Bearer tok123"
    body = json.loads(req.content)
    assert set(body) == {"header", "body", "footer", "buttonText", "sections"}  # additionalProperties:false in WATI's schema
    assert body["buttonText"] == "Select SO" and body["sections"][0]["title"] == "Your orders"
    assert body["sections"][0]["rows"] == [{"title": "SO 45240", "description": "3 items"}, {"title": "SO 45231", "description": "1 item"}]
    assert all(set(r) == {"title", "description"} for r in body["sections"][0]["rows"])  # no 'id' key
    assert live_wati.outbox[-1]["kind"] == "list" and live_wati.outbox[-1]["sent"] is True


@pytest.mark.asyncio
async def test_buttons_uses_query_param_and_documented_body(live_wati):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{BASE}/api/v1/sendInteractiveButtonsMessage").mock(return_value=Response(200, json={"ok": True}))
        await live_wati.send_buttons("919876543210", "Confirm?", menus.confirm_buttons("en"))
    req = route.calls.last.request
    assert req.url.params["whatsappNumber"] == "919876543210"
    assert json.loads(req.content) == {"body": "Confirm?", "buttons": [{"text": "Yes"}, {"text": "No"}]}


@pytest.mark.asyncio
async def test_bearer_prefix_not_doubled(live_wati, monkeypatch):
    monkeypatch.setenv("WATI_TOKEN", "Bearer abc")
    get_settings.cache_clear()
    with respx.mock() as mock:
        route = mock.post(f"{BASE}/api/v1/sendSessionMessage/91").mock(return_value=Response(200, json={"ok": True, "result": "success"}))
        await live_wati.send_text("91", "hi")
    assert route.calls.last.request.headers["Authorization"] == "Bearer abc"
    assert route.calls.last.request.url.params["messageText"] == "hi"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [Response(400, json={"ok": False, "result": "bad"}), Response(200, json={"ok": False, "result": "Invalid"}), Response(500, text="boom")])
async def test_interactive_failure_falls_back_to_text_with_options(live_wati, response):
    opts = menus.after_result_buttons("en")
    with respx.mock() as mock:
        mock.post(f"{BASE}/api/v1/sendInteractiveButtonsMessage").mock(return_value=response)
        text_route = mock.post(f"{BASE}/api/v1/sendSessionMessage/91").mock(return_value=Response(200, json={"ok": True}))
        await live_wati.send_buttons("91", "Status: x", opts)
    sent = text_route.calls.last.request.url.params["messageText"]
    assert sent.startswith("Status: x") and "• Check another SO" in sent and "• Done" in sent


@pytest.mark.asyncio
async def test_text_send_retries_on_5xx_then_succeeds(live_wati):
    with respx.mock() as mock:
        route = mock.post(f"{BASE}/api/v1/sendSessionMessage/91")
        route.side_effect = [Response(502, text="bad gateway"), Response(200, json={"ok": True})]
        await live_wati.send_text("91", "hi")
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_v3_interactive_payloads(live_wati, monkeypatch):
    monkeypatch.setenv("WATI_API_VERSION", "v3")
    get_settings.cache_clear()
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{BASE}/api/ext/v3/conversations/messages/interactive").mock(return_value=Response(200, json={"message": {"id": "x"}}))
        await live_wati.send_list("919", "Pick", menus.Options(kind="list", items=[menus.Option("SO 1", "d")], button_text="Select", section_title="S"))
        await live_wati.send_buttons("919", "Confirm?", menus.confirm_buttons("gu"))
    lst = json.loads(route.calls[0].request.content)
    assert lst["target"] == "919" and lst["type"] == "list" and lst["list_message"]["button_text"] == "Select"
    assert lst["list_message"]["sections"][0]["rows"] == [{"title": "SO 1", "description": "d"}]
    btn = json.loads(route.calls[1].request.content)
    assert btn["type"] == "buttons" and btn["button_message"]["buttons"] == [{"text": "હા"}, {"text": "ના"}]
    assert "whatsappNumber" not in str(route.calls[0].request.url)
