"""
ingestion/embedder.py
Szöveg darabolása és vektorizálása — a rendszer motorja.
"""
import hashlib
import os
from typing import Any

import tiktoken
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM   = int(os.getenv("EMBEDDING_DIM", 1536))
COLLECTION      = os.getenv("QDRANT_COLLECTION", "second_brain")
CHUNK_SIZE      = 400   # tokenben
CHUNK_OVERLAP   = 60    # tokenben


def _get_qdrant() -> QdrantClient:
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", 6333))
    return QdrantClient(host=host, port=port)


def ensure_collection() -> None:
    """Létrehozza a kollekciót, ha még nem létezik."""
    client = _get_qdrant()
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"[Qdrant] '{COLLECTION}' kollekció létrehozva.")


def chunk_text(text: str) -> list[str]:
    """Szöveg darabolása átfedéssel, token-alapon."""
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    chunks = []
    for i in range(0, len(tokens), CHUNK_SIZE - CHUNK_OVERLAP):
        chunk_tokens = tokens[i : i + CHUNK_SIZE]
        chunk = enc.decode(chunk_tokens)
        if len(chunk.strip()) > 30:          # nagyon rövid töredékeket kihagyjuk
            chunks.append(chunk.strip())
    return chunks


def _stable_id(source: str, chunk_idx: int) -> int:
    """Reprodukálható, ütközésmentes pont-ID generálás."""
    raw = f"{source}::{chunk_idx}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:15], 16)


def embed_and_store(
    text: str,
    metadata: dict[str, Any],
    source_id: str | None = None,
) -> int:
    """
    Szöveget darabolja, vektorizálja, Qdrant-ba tölti.
    Visszaadja a betöltött chunk-ok számát.
    """
    ensure_collection()
    oai    = OpenAI()
    client = _get_qdrant()

    chunks = chunk_text(text)
    if not chunks:
        return 0

    sid = source_id or metadata.get("source", "unknown")

    # Batch embedding (max 100 chunk / hívás az OpenAI limitje miatt)
    points: list[PointStruct] = []
    batch_size = 50
    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start : batch_start + batch_size]
        response = oai.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        for rel_idx, emb_obj in enumerate(response.data):
            abs_idx  = batch_start + rel_idx
            point_id = _stable_id(sid, abs_idx)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=emb_obj.embedding,
                    payload={
                        "text":   batch[rel_idx],
                        "chunk":  abs_idx,
                        "total_chunks": len(chunks),
                        **metadata,
                    },
                )
            )

    client.upsert(collection_name=COLLECTION, points=points)
    return len(points)
