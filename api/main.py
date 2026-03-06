"""
api/main.py
FastAPI REST API — n8n és Telegram bot számára.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
def query_kb(req: QueryRequest):
    """
    Kérdés feltevése a tudásbázisnak.
    Ezt hívja az n8n Telegram workflow.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Üres kérdés.")
    result = query(req.question, top_k=req.top_k)
    return QueryResponse(
        answer=req.question and result.answer,
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
