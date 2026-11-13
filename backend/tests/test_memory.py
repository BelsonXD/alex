"""Memory storage, edit, delete, and retrieval ranking."""

from alex.memory.embeddings import hash_embed, score_memory
from alex.memory.service import extract_explicit, extract_soft


def test_hash_embedding_is_stable_and_normalized():
    first = hash_embed("Sahib prefers jasmine tea")
    second = hash_embed("Sahib prefers jasmine tea")
    assert first == second
    assert abs(sum(value * value for value in first) - 1) < 1e-6


def test_retrieval_ranks_the_relevant_memory(client):
    client.post("/api/memories", json={"content": "Sahib prefers jasmine tea in the evening", "kind": "preference"})
    client.post("/api/memories", json={"content": "The reactor coil serial is RK-19", "kind": "fact"})
    ranked = client.get("/api/memories", params={"q": "what tea does Sahib like"}).json()
    assert ranked[0]["content"].startswith("Sahib prefers jasmine tea")
    assert score_memory("jasmine tea", ranked[0]["content"], "{}") > score_memory(
        "jasmine tea", "The reactor coil serial is RK-19", "{}"
    )


def test_memory_edit_and_delete(client):
    created = client.post("/api/memories", json={"content": "Desk faces the window", "kind": "fact"}).json()
    updated = client.put(
        f"/api/memories/{created['id']}",
        json={"content": "Desk faces the north window", "kind": "fact"},
    ).json()
    assert updated["content"] == "Desk faces the north window"
    assert client.delete(f"/api/memories/{created['id']}").status_code == 200
    assert client.get("/api/memories").json() == []


def test_explicit_and_soft_extraction():
    assert extract_explicit("Please remember that Sahib drinks tea.") == ["Sahib drinks tea"]
    soft = extract_soft("I prefer night shifts and quiet rooms")
    assert soft and soft[0][0] == "preference"
    assert "night shifts" in soft[0][1].lower()


def test_chat_remember_is_saved_once(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": "Remember that Sahib prefers jasmine tea"})
        kinds = []
        while True:
            message = ws.receive_json()
            kinds.append(message["type"])
            if message["type"] in {"done", "error"}:
                assert message["type"] == "done"
                break
    memories = client.get("/api/memories").json()
    assert len(memories) == 1
    assert "jasmine tea" in memories[0]["content"]
    assert "tool" in kinds
