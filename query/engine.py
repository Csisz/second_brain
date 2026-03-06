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


def query(question: str, top_k: int = TOP_K, allowed_collections: list[str] | None = None) -> QueryResult:
    """
    Kérdésre válaszol a tudásbázis alapján.
    allowed_collections: ha meg van adva, csak ezekből a source_tag-ekből keres.
    None esetén minden kollekció elérhető (n8n / bot hívások).
    """
    from qdrant_client.models import Filter, FieldCondition, MatchAny

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

    # 2. Kollekció szűrő összerakása
    query_filter = None
    if allowed_collections is not None:
        if len(allowed_collections) == 0:
            return QueryResult(
                answer="Nincs hozzáférése egyetlen kollekcióhoz sem.",
                sources=[],
                chunks_used=0,
                model=CLAUDE_MODEL,
            )
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="source_tag",
                    match=MatchAny(any=allowed_collections),
                )
            ]
        )

    # 3. Keresés a vektoros adatbázisban
    hits = qdrant.query_points(
        collection_name=COLLECTION,
        query=q_vec,
        limit=top_k,
        with_payload=True,
        query_filter=query_filter,
    ).points

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
        # vectors_count vagy points_count — verziófüggő
        count = getattr(info, "vectors_count", None) \
             or getattr(info, "points_count", None) \
             or info.config.params.vectors.size
        return {
            "collection":    COLLECTION,
            "total_vectors": count,
            "status":        str(info.status),
        }
    except Exception as e:
        # Próbáljuk meg a collection_info-val
        try:
            result = qdrant.count(collection_name=COLLECTION)
            return {
                "collection":    COLLECTION,
                "total_vectors": result.count,
                "status":        "green",
            }
        except Exception:
            return {"collection": COLLECTION, "total_vectors": 0, "status": "not_found"}