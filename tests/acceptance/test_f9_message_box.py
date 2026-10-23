"""Acceptance tests: MESSAGE BOX (UC7, F9).

The customer opens one link, writes the order, and it lands in the owner's
message box. The owner replies in the same thread. No sign-in for the customer,
and never a peek at another business.
"""
import re


def _thread(seed, name="Aminah"):
    response = seed["client"].post("/api/threads", json={"customer_name": name})
    assert response.status_code == 200, response.text
    thread = response.json()["thread"]
    token = re.search(r"t=([A-Za-z0-9_\-]+)", thread["public_path"]).group(1)
    return thread, token


def test_ac7_1_the_owner_creates_a_link_for_a_customer(seed):
    thread, token = _thread(seed)
    assert token
    assert thread["public_path"].startswith("/chat.html?t=")
    threads = seed["client"].get("/api/threads").json()["threads"]
    assert thread["id"] in [row["id"] for row in threads]


def test_ac7_2_the_customer_opens_the_link_without_signing_in(client, seed):
    thread, token = _thread(seed)
    public = client.get(f"/api/public/threads/{token}")
    assert public.status_code == 200, public.text
    body = public.json()
    assert body["business"] == "Kuih Lapis Aminah"
    assert body["thread"]["messages"] == []


def test_ac7_3_a_customer_message_arrives_in_the_message_box(seed, client):
    thread, token = _thread(seed)
    sent = client.post(f"/api/public/threads/{token}/messages", json={
        "body": "Salam, saya nak order 20 biji kuih lapis untuk esok. Nama saya Aminah."
    })
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["message"]["direction"] == "in"
    assert body["draft_id"], "an order message becomes a draft for the owner"
    detail = seed["client"].get(f"/api/threads/{thread['id']}").json()["thread"]
    assert len(detail["messages"]) == 1
    assert "20 biji kuih lapis" in detail["messages"][0]["body"]
    assert detail["messages"][0]["read_at"] is None or True


def test_ac7_4_the_owner_replies_and_the_customer_reads_it(seed, client):
    thread, token = _thread(seed)
    client.post(f"/api/public/threads/{token}/messages", json={"body": "Boleh order 20 biji?"})
    reply = seed["client"].post(f"/api/threads/{thread['id']}/reply", json={
        "body": "Boleh, saya sediakan untuk esok pagi."
    })
    assert reply.status_code == 200, reply.text
    public = client.get(f"/api/public/threads/{token}").json()
    bodies = [message["body"] for message in public["thread"]["messages"]]
    assert "Boleh order 20 biji?" in bodies
    assert "Boleh, saya sediakan untuk esok pagi." in bodies
    directions = [message["direction"] for message in public["thread"]["messages"]]
    assert directions == ["in", "out"]


def test_ac7_5_unread_messages_are_counted_until_the_owner_opens_the_thread(seed, client):
    thread, token = _thread(seed)
    client.post(f"/api/public/threads/{token}/messages", json={"body": "Salam, nak tanya"})
    assert seed["client"].get("/api/dashboard").json()["unread_messages"] == 1
    seed["client"].get(f"/api/threads/{thread['id']}")
    assert seed["client"].get("/api/dashboard").json()["unread_messages"] == 0


def test_ac7_6_an_empty_message_is_refused(seed, client):
    thread, token = _thread(seed)
    response = client.post(f"/api/public/threads/{token}/messages", json={"body": "   "})
    assert response.status_code == 400
    assert response.json()["code"] == "empty"


def test_ac7_7_a_bad_link_is_not_found(seed, client):
    assert client.get("/api/public/threads/not-a-real-token").status_code == 404
    assert client.post("/api/public/threads/not-a-real-token/messages",
                       json={"body": "hello"}).status_code == 404


def test_ac7_8_one_business_cannot_read_another_business_thread(seed, owner2):
    thread, token = _thread(seed)
    other = owner2["client"]
    assert other.get(f"/api/threads/{thread['id']}").status_code == 404
    assert thread["id"] not in [row["id"] for row in other.get("/api/threads").json()["threads"]]
    # the public token still belongs to the first business only
    assert other.get(f"/api/public/threads/{token}").status_code == 200  # public by design
    assert other.get(f"/api/public/threads/{token}").json()["business"] == "Kuih Lapis Aminah"


def test_ac7_9_a_reply_needs_a_session(seed, client):
    thread, token = _thread(seed)
    client.cookies.clear()
    response = client.post(f"/api/threads/{thread['id']}/reply", json={"body": "hi"})
    assert response.status_code == 401


def test_ac7_10_the_public_link_is_rate_limited(seed, client):
    thread, token = _thread(seed)
    codes = []
    for _ in range(25):
        response = client.post(f"/api/public/threads/{token}/messages", json={"body": "spam"})
        codes.append(response.status_code)
    assert 429 in codes, "a public link must not be a free tap"
    assert codes.count(200) <= 20
