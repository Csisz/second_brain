"""
query/engine.py
RAG lekérdező motor — Qdrant keresés + Claude válasz.
"""
import os
from dataclasses import dataclass

import anthropic
from openai import OpenAI
from qdrant_client import QdrantClient

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
COLLECTION      = os.getenv("QDRANT_COLLECTION", "second_brain")
CLAUDE_MODEL    = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
TOP_K           = 6   # hány chunk-ot adjunk a Claude-nak kontextusként

SYSTEM_PROMPT = """Te egy személyes AI asszisztens vagy, aki az informatikai tanácsadó 
saját dokumentumain, e-mailjein és munkafájljain alapuló tudásbázisból válaszol.

Szabályok:
- Csak a megadott kontextusban lévő információkra alapozz.
- Ha a kontextus nem tartalmaz elég információt, mondd meg egyértelműen.
- Mindig jelöld meg, melyik forrásból (e-mail tárgy, fájlnév) származik az info.
- Válaszolj magyarán, tömören és pontosan.
- Ha több releváns forrás van, összegezd őket."""


@dataclass
class QueryResult:
    answer: str
    sources: list[str]
    chunks_used: int
    model: str


def query(question: str, top_k: int = TOP_K) -> QueryResult:
    """
    Kérdésre válaszol a tudásbázis alapján.
    1. Vektorizálja a kérdést
    2. Megkeresi a leginkább releváns chunk-okat
    3. Claude-dal választ generál
    """
    oai     = OpenAI()
    qdrant  = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333)),
    )
    claude  = anthropic.Anthropic()

    # 1. Kérdés vektorizálása
    q_vec = oai.embeddings.create(
        model=EMBEDDING_MODEL, input=question
    ).data[0].embedding

    # 2. Keresés a vektoros adatbázisban
    hits = qdrant.search(
        collection_name=COLLECTION,
        query_vector=q_vec,
        limit=top_k,
        with_payload=True,
    )

    if not hits:
        return QueryResult(
            answer="A tudásbázis még üres, vagy nem találtam releváns dokumentumot.",
            sources=[],
            chunks_used=0,
            model=CLAUDE_MODEL,
        )

    # 3. Kontextus összerakása forrás-annotációkkal
    context_parts = []
    sources       = []
    for i, hit in enumerate(hits, 1):
        src   = hit.payload.get("source", "ismeretlen forrás")
        date  = hit.payload.get("date", hit.payload.get("indexed_at", ""))[:10]
        ftype = hit.payload.get("file_type", "")
        label = f"{src}" + (f" [{date}]" if date else "")
        context_parts.append(f"[{i}] {label}\n{hit.payload['text']}")
        if label not in sources:
            sources.append(label)

    context = "\n\n---\n\n".join(context_parts)

    # 4. Claude API hívás
    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Kontextus (releváns dokumentumrészletek):\n\n{context}\n\n"
                       f"Kérdés: {question}",
        }],
    )

    return QueryResult(
        answer=response.content[0].text,
        sources=sources,
        chunks_used=len(hits),
        model=CLAUDE_MODEL,
    )


def get_collection_stats() -> dict:
    """Visszaadja a kollekció aktuális állapotát."""
    qdrant = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333)),
    )
    try:
        info = qdrant.get_collection(COLLECTION)
        return {
            "collection":    COLLECTION,
            "total_vectors": info.vectors_count,
            "status":        str(info.status),
        }
    except Exception:
        return {"collection": COLLECTION, "total_vectors": 0, "status": "not_found"}
