"""The shop assistant: grounding, tidying, and the two endpoints (Flowise)."""
import json

import dataclasses

import httpx
import pytest

from app import bot as bot_service
from app.bot import (BotClient, BotError, BotFacts, build_question, guard,
                     parse_history, tidy)


def test_the_context_carries_the_shops_real_menu():
    facts = BotFacts(
        name="Dapur Aminah", address="12 Jalan Melati", phone="+60123456789",
        tagline="Kuih setiap pagi", shop_url="http://localhost:8000/shop?b=dapur-aminah",
        dishes=[{"name": "Kuih Lapis", "price": "12.00", "category": "Kuih",
                 "description": "Box of ten"}],
    )
    context = facts.as_context()
    assert "Kuih Lapis — RM12.00" in context
    assert "12 Jalan Melati" in context
    assert "+60123456789" in context
    assert "dapur-aminah" in context
    assert "RM4.00" in context


def test_hours_come_from_the_shop_or_say_unknown():
    with_hours = BotFacts(name="Dapur Aminah", hours="9:00 pagi – 6:00 petang")
    assert "9:00 pagi – 6:00 petang" in with_hours.as_context()
    without = BotFacts(name="Dapur Aminah")
    assert "tidak dinyatakan" in without.as_context()
    assert "Jangan reka waktu buka" in without.as_context()


def test_a_dropped_closing_day_is_appended_back():
    facts = BotFacts(name="Dapur Aminah", hours="Setiap hari, 9:00 pagi – 6:00 petang (tutup hari Isnin)")
    dropped = guard("Kami buka setiap hari dari 9:00 pagi hingga 6:00 petang.", facts,
                    "Buka hari apa dan pukul berapa?")
    assert "tutup hari Isnin" in dropped
    kept = guard("Kami tutup hari Isnin, buka 9:00 pagi – 6:00 petang.", facts, "Buka pukul berapa?")
    assert kept == "Kami tutup hari Isnin, buka 9:00 pagi – 6:00 petang."
    other = guard("Kuih lapis RM12.00.", facts, "Harga kuih lapis?")
    assert other == "Kuih lapis RM12.00."


def test_a_missing_delivery_fee_is_appended_back():
    facts = BotFacts(name="Dapur Aminah", delivery_fee="4.00")
    fixed = guard("Ya, kami hantar ke Kajang.", facts, "Boleh hantar ke Kajang?")
    assert "RM4.00" in fixed and "percuma" in fixed
    said = guard("Hantar RM4.00, pickup percuma.", facts, "Berapa penghantaran?")
    assert said == "Hantar RM4.00, pickup percuma."


def test_the_question_forbids_inventing_and_carries_history():
    facts = BotFacts(name="Dapur Aminah", dishes=[{"name": "Nasi Lemak", "price": "7.50"}])
    question = build_question(
        facts, "Boleh hantar ke Kajang?",
        [{"role": "user", "text": "Harga kuih lapis?"}, {"role": "bot", "text": "RM12 sekotak."}],
    )
    assert "SOALAN PELANGGAN" in question
    assert "Boleh hantar ke Kajang?" in question
    assert "Jangan reka harga" in question
    assert "RM7.50" in question
    assert "Harga kuih lapis?" in question          # earlier turn kept
    assert question.index("KONTEKS KEDAI") < question.index("ARAHAN")


def test_tidy_strips_the_chatty_preamble_and_markdown():
    raw = "Berikut adalah ringkasan yang lebih natural dan mudah difahami:\n\n**Kuih Lapis** RM12.00 sekotak."
    assert tidy(raw) == "Kuih Lapis RM12.00 sekotak."
    assert tidy("### Menu\n\n- Nasi Lemak RM7.50") == "Menu\n\n- Nasi Lemak RM7.50"
    assert tidy("*tentu* boleh") == "boleh"


def test_tidy_caps_a_runaway_reply():
    assert len(tidy("ayat. " * 400)) <= bot_service.MAX_REPLY


def test_history_is_trimmed_and_typed():
    raw = [{"role": "user", "text": "a" * 500}, {"role": "bot", "text": "ok"},
           {"role": "weird", "text": "hi"}, {"text": ""}, "junk"]
    out = parse_history(raw)
    assert out[0] == {"role": "user", "text": "a" * 300}
    assert out[1] == {"role": "bot", "text": "ok"}
    assert out[2] == {"role": "user", "text": "hi"}
    assert len(out) == 3


def _client(handler, timeout=10.0):
    return BotClient(
        type("S", (), {"flowise_url": "https://flow.test/api/v1/prediction/x",
                       "flowise_api_key": "k", "flowise_timeout_seconds": timeout})(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_the_flow_payload_is_proxied_and_the_text_extracted():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"text": "  Kuih lapis RM12.00.  ", "chatId": "c1"})

    text, ms = _client(handler).reply("soalan", "sess-1")
    assert text == "Kuih lapis RM12.00."
    assert seen["body"]["question"] == "soalan"
    assert seen["body"]["sessionId"] == "sess-1"
    assert seen["auth"] == "Bearer k"
    assert ms >= 0


def test_a_broken_flow_becomes_a_clear_error():
    with pytest.raises(BotError) as info:
        _client(lambda r: httpx.Response(500, json={"error": "boom"})).reply("hi")
    assert info.value.code == "bot_failed" and info.value.status == 502

    with pytest.raises(BotError) as info:
        _client(lambda r: httpx.Response(200, json={"text": "   "})).reply("hi")
    assert info.value.code == "bot_empty"

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(BotError) as info:
        _client(timeout).reply("hi")
    assert info.value.code == "bot_timeout" and info.value.status == 504


def test_an_unconfigured_bot_says_so():
    client = BotClient(type("S", (), {"flowise_url": "", "flowise_api_key": "",
                                      "flowise_timeout_seconds": 5.0})())
    assert client.configured is False
    with pytest.raises(BotError) as info:
        client.reply("hi")
    assert info.value.status == 503


# ------------------------------------------------------------------ endpoints

@pytest.fixture
def bot_on(seed):
    """The app factory reads settings per request, so swap in a configured one."""
    app = seed["client"].app
    app.state.settings = dataclasses.replace(
        app.state.settings, bot_enabled=True,
        flowise_url="https://flow.test/api/v1/prediction/x", flowise_api_key="k")
    return seed

def _facts(seed):
    client = seed["client"]
    client.post("/api/products", json={"name": "Kuih Lapis", "price": 12.0, "category": "Kuih"})
    return client.get("/api/settings/business").json()


def test_the_seller_asks_the_assistant(bot_on, monkeypatch):
    calls = {}

    def fake_reply(self, question, session_id=None):
        calls["question"] = question
        calls["session"] = session_id
        return "Kuih Lapis RM12.00 sekotak.", 42

    monkeypatch.setattr(BotClient, "reply", fake_reply)
    _facts(bot_on)
    response = bot_on["client"].post("/api/bot/chat", json={
        "message": "Berapa harga kuih lapis?", "session_id": "abc-123",
        "history": [{"role": "user", "text": "hai"}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == "Kuih Lapis RM12.00 sekotak."
    assert "Kuih Lapis — RM12.00" in calls["question"]      # grounded on our menu
    assert calls["session"] == "abc-123"
    assert bot_on["client"].get("/api/bot/chat").status_code == 403   # deny by default


def test_the_assistant_needs_a_signed_in_seller(client, monkeypatch):
    monkeypatch.setattr(BotClient, "reply", lambda *a, **k: ("hi", 1))
    assert client.post("/api/bot/chat", json={"message": "hi"}).status_code == 401


def test_a_buyer_asks_from_the_shop_page(bot_on, monkeypatch):
    shop = _facts(bot_on)
    monkeypatch.setattr(BotClient, "reply", lambda self, q, s=None: ("Boleh, RM4.00.", 30))
    response = bot_on["client"].post(f"/api/public/shops/{shop['slug']}/bot",
                                     json={"message": "Hantar ke Kajang?"})
    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "Boleh, RM4.00."


def test_a_shop_that_does_not_exist_is_a_404(seed):
    response = seed["client"].post("/api/public/shops/nope/bot", json={"message": "hi"})
    assert response.status_code == 404
    assert response.json()["code"] == "no_shop"


def test_the_public_bot_is_rate_limited(bot_on, monkeypatch):
    shop = _facts(bot_on)
    monkeypatch.setattr(BotClient, "reply", lambda self, q, s=None: ("ok", 1))
    codes = [bot_on["client"].post(f"/api/public/shops/{shop['slug']}/bot",
                                 json={"message": f"soalan {i}"}).status_code for i in range(21)]
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


def test_the_assistant_can_be_switched_off(bot_on, monkeypatch):
    monkeypatch.setattr(BotClient, "reply", lambda self, q, s=None: ("ok", 1))
    app = bot_on["client"].app
    app.state.settings = dataclasses.replace(app.state.settings, bot_enabled=False)
    response = bot_on["client"].post("/api/bot/chat", json={"message": "hi"})
    assert response.status_code == 503
    assert response.json()["code"] == "bot_off"
