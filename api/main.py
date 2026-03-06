"""
api/main.py
FastAPI REST API — n8n és Telegram bot számára.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# Optional auth — nem dob hibát ha nincs token (n8n kompatibilitás)
security_optional = HTTPBearer(auto_error=False)

load_dotenv()

from query.engine import query, get_collection_stats
from ingestion.embedder import embed_and_store, ensure_collection
from ingestion.file_readers import read_file
from ingestion.folder_scanner import scan_folder

app = FastAPI(
    title="Second Brain API",
    description="Személyes AI tudásbázis — RAG alapú lekérdező rendszer",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Modellek ───────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str
    top_k: Optional[int] = 6


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    chunks_used: int
    model: str


class IngestTextRequest(BaseModel):
    text: str
    source: str
    source_tag: Optional[str] = "manual"
    file_type: Optional[str] = "text"


class ScanRequest(BaseModel):
    folder: str
    force_reindex: Optional[bool] = False
    source_tag: Optional[str] = "nas_munka"


# ─── Endpointok ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "Second Brain API"}


@app.get("/health")
def health():
    stats = get_collection_stats()
    return {"status": "healthy", **stats}


@app.post("/query", response_model=QueryResponse)
def query_kb(
    req: QueryRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security_optional),
):
    """
    Kérdés feltevése a tudásbázisnak.
    Ha van JWT token, csak az engedélyezett kollekciókból keres.
    Token nélkül (n8n) teljes hozzáférés.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Üres kérdés.")

    allowed_collections = None  # None = minden kollekció (n8n/bot)
    if credentials:
        try:
            from auth.jwt_handler import decode_token
            from auth.database import get_user_collections, SessionLocal
            payload = decode_token(credentials.credentials)
            user_id = payload.get("sub")
            if user_id:
                db = SessionLocal()
                try:
                    allowed_collections = get_user_collections(db, user_id)
                finally:
                    db.close()
        except Exception:
            pass  # érvénytelen token → nyílt lekérdezés

    result = query(req.question, top_k=req.top_k, allowed_collections=allowed_collections)
    return QueryResponse(
        answer=result.answer,
        sources=result.sources,
        chunks_used=result.chunks_used,
        model=result.model,
    )


@app.post("/ingest/text")
def ingest_text(req: IngestTextRequest):
    """Szöveges tartalom közvetlen betöltése (pl. n8n Gmail workflow)."""
    ensure_collection()
    from datetime import datetime
    metadata = {
        "source":     req.source,
        "source_tag": req.source_tag,
        "file_type":  req.file_type,
        "indexed_at": datetime.now().isoformat(),
    }
    n = embed_and_store(req.text, metadata)
    return {"status": "ok", "chunks_stored": n, "source": req.source}


@app.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    """Fájl feltöltése és betöltése (drag & drop teszteléshez)."""
    ensure_collection()
    from datetime import datetime

    tmp_path = Path(f"/tmp/{file.filename}")
    tmp_path.write_bytes(await file.read())

    text = read_file(tmp_path)
    tmp_path.unlink(missing_ok=True)

    if not text:
        raise HTTPException(status_code=422, detail=f"Nem olvasható fájlformátum: {file.filename}")

    suffix = Path(file.filename).suffix.lower().lstrip(".")
    metadata = {
        "source":     file.filename,
        "source_tag": "upload",
        "file_type":  suffix,
        "indexed_at": datetime.now().isoformat(),
    }
    n = embed_and_store(text, metadata)
    return {"status": "ok", "chunks_stored": n, "filename": file.filename}


@app.post("/ingest/scan")
def ingest_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    """
    Mappa rekurzív szkennelése háttérben.
    Pl. a NAS MUNKA mappájára mutatva.
    """
    if not Path(req.folder).exists():
        raise HTTPException(status_code=404, detail=f"Mappa nem létezik: {req.folder}")
    background_tasks.add_task(
        scan_folder,
        folder=req.folder,
        force_reindex=req.force_reindex,
        source_tag=req.source_tag,
    )
    return {"status": "scanning_started", "folder": req.folder}


@app.get("/stats")
def stats():
    """Tudásbázis statisztikák."""
    return get_collection_stats()


class GmailSyncRequest(BaseModel):
    days_back: Optional[int] = 1
    max_emails: Optional[int] = 500
    recipient: Optional[str] = "viktor.huszar@user.hu"


@app.post("/ingest/gmail")
def ingest_gmail(req: GmailSyncRequest, background_tasks: BackgroundTasks):
    """
    Gmail szinkronizálás indítása háttérben.
    Ezt hívja az n8n Gmail Ingestion workflow.
    """
    from ingestion.gmail_reader import sync_gmail
    background_tasks.add_task(
        sync_gmail,
        days_back=req.days_back,
        max_emails=req.max_emails,
        recipient=req.recipient,
    )
    return {
        "status": "gmail_sync_started",
        "days_back": req.days_back,
        "recipient": req.recipient,
        "loaded": 0,
        "skipped": 0,
    }


# ─── Minőségellenőrző endpointok ────────────────────────────────────────────

from datetime import datetime, timedelta
from collections import defaultdict


@app.get("/quality/stats")
def quality_stats():
    """Részletes statisztika a minőségellenőrző workflow számára."""
    from qdrant_client import QdrantClient

    client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333)),
    )
    collection = os.getenv("QDRANT_COLLECTION", "second_brain")

    all_points = []
    offset = None
    while True:
        result, offset = client.scroll(
            collection_name=collection,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        all_points.extend(result)
        if offset is None:
            break

    tag_counts = defaultdict(int)
    source_dates = {}
    source_chunks = defaultdict(int)

    for point in all_points:
        payload = point.payload or {}
        tag = payload.get("source_tag", "unknown")
        tag_counts[tag] += 1
        source = payload.get("source", "")
        indexed_at = payload.get("indexed_at", "")
        source_chunks[source] += 1
        if source and indexed_at:
            if source not in source_dates or indexed_at < source_dates[source]:
                source_dates[source] = indexed_at

    cutoff = (datetime.now() - timedelta(days=180)).isoformat()
    outdated = [
        {"source": src, "indexed_at": dt, "chunks": source_chunks[src]}
        for src, dt in source_dates.items()
        if dt < cutoff
    ]
    outdated.sort(key=lambda x: x["indexed_at"])

    source_names = list(source_chunks.keys())
    duplicate_suspects = []
    seen = set()
    for i, s1 in enumerate(source_names):
        if s1 in seen:
            continue
        name1 = s1.lower().replace("\\", "/").split("/")[-1]
        for s2 in source_names[i+1:]:
            name2 = s2.lower().replace("\\", "/").split("/")[-1]
            if name1 == name2 and s1 != s2:
                duplicate_suspects.append({"source1": s1, "source2": s2, "filename": name1})
                seen.add(s1)
                seen.add(s2)

    total = len(all_points)
    issues = len(outdated) + len(duplicate_suspects)
    health = max(0, 100 - (issues / max(total, 1) * 1000))

    return {
        "generated_at": datetime.now().isoformat(),
        "total_vectors": total,
        "total_sources": len(source_chunks),
        "tag_breakdown": dict(tag_counts),
        "outdated_docs": outdated[:20],
        "duplicate_suspects": duplicate_suspects[:20],
        "oldest_docs": sorted(
            [{"source": s, "indexed_at": d} for s, d in source_dates.items()],
            key=lambda x: x["indexed_at"]
        )[:10],
        "issues_count": issues,
        "health_score": round(health, 1),
    }


@app.get("/quality/coverage")
def quality_coverage():
    """Kollekció lefedettség elemzés tag-enkénti bontásban."""
    from qdrant_client import QdrantClient

    client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333)),
    )
    collection = os.getenv("QDRANT_COLLECTION", "second_brain")

    expected_tags = ["telenor", "yettel", "mvmi", "egis", "extended_ecm",
                     "oscript", "telenor_dk", "gmail"]
    tag_counts = defaultdict(int)

    offset = None
    while True:
        result, offset = client.scroll(
            collection_name=collection,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in result:
            tag = (point.payload or {}).get("source_tag", "unknown")
            tag_counts[tag] += 1
        if offset is None:
            break

    coverage = {}
    missing = []
    for tag in expected_tags:
        count = tag_counts.get(tag, 0)
        coverage[tag] = count
        if count == 0:
            missing.append(tag)

    return {
        "coverage": coverage,
        "missing_collections": missing,
        "extra_collections": [t for t in tag_counts if t not in expected_tags],
        "total_vectors": sum(tag_counts.values()),
    }


# ─── Auth router ────────────────────────────────────────────────────────────

from auth.router import router as auth_router
from auth.database import init_db

app.include_router(auth_router)


@app.on_event("startup")
def startup_event():
    """DB inicializálás induláskor."""
    init_db()
    print("[Auth] PostgreSQL DB inicializálva")