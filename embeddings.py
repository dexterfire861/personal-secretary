import json
from pathlib import Path
from urllib.request import Request, urlopen

import chromadb

OLLAMA_HOST = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
CHROMA_PATH = Path(__file__).with_name("chroma_store")
COLLECTION_NAME = "memories"

_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
_collection = _client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},
)


def embed(text: str) -> list[float]:
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")
    payload = json.dumps({"model": EMBED_MODEL, "input": text}).encode()
    req = Request(
        f"{OLLAMA_HOST}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["embeddings"][0]


def upsert(msg_id: int, text: str):
    vector = embed(text)
    _collection.upsert(
        ids=[str(msg_id)],
        embeddings=[vector],
        documents=[text],
    )


def query_similar(text: str, n: int) -> list[tuple[int, float]]:
    vector = embed(text)
    results = _collection.query(
        query_embeddings=[vector],
        n_results=min(n, _collection.count()),
    )
    if not results["ids"] or not results["ids"][0]:
        return []
    return [
        (int(id_), dist)
        for id_, dist in zip(results["ids"][0], results["distances"][0])
    ]
