"""Hashing-trick embeddings, with an optional OpenAI embedding backend.

The local vector is always available, so retrieval works with no API key.
When an OpenAI key is set, memories are embedded with text-embedding-3-small
and compared in that space. Stored vectors remember which model produced them.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

import httpx

DIMS = 256
HASH_MODEL = "hash-256"
OPENAI_MODEL = "text-embedding-3-small"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def hash_embed(text: str, dims: int = DIMS) -> list[float]:
    vec = [0.0] * dims
    tokens = tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


def pack(model: str, vector: list[float]) -> str:
    return json.dumps({"model": model, "vector": vector})


def unpack(payload: str) -> tuple[str, list[float]]:
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return HASH_MODEL, []
    vector = data.get("vector") or []
    if not isinstance(vector, list):
        return HASH_MODEL, []
    return str(data.get("model") or HASH_MODEL), [float(v) for v in vector]


async def openai_embed(text: str, api_key: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": OPENAI_MODEL, "input": text},
        )
        response.raise_for_status()
        data = response.json()
        return list(data["data"][0]["embedding"])


def embed_sync(text: str) -> tuple[str, list[float]]:
    """Local embedding used on the request path so chat never blocks on a network embed."""
    return HASH_MODEL, hash_embed(text)


def score_memory(query: str, content: str, stored_payload: str) -> float:
    model, vector = unpack(stored_payload)
    q_model, q_vec = embed_sync(query)
    if model != q_model or not vector:
        vector = hash_embed(content)
        q_vec = hash_embed(query)
    lexical = _overlap(query, content)
    return cosine(q_vec, vector) + 0.35 * lexical


def _overlap(query: str, content: str) -> float:
    q = set(tokenize(query))
    c = set(tokenize(content))
    if not q or not c:
        return 0.0
    return len(q & c) / len(q)


def embedding_payload(text: str) -> str:
    model, vector = embed_sync(text)
    return pack(model, vector)


def describe_backend(openai_key: str) -> dict[str, Any]:
    if openai_key:
        return {
            "active": HASH_MODEL,
            "openai_available": True,
            "note": "Retrieval uses the local hashing embedder so it stays instant. OpenAI embeddings can be enabled later without changing stored memories.",
        }
    return {
        "active": HASH_MODEL,
        "openai_available": False,
        "note": "Local hashing embedder. Add an OpenAI key if you later want hosted embeddings.",
    }
