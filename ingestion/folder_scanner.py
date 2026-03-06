"""
ingestion/folder_scanner.py
Helyi mappa (vagy NAS mount) rekurzív feldolgozása.
Nyomon követi, mely fájlokat dolgoztuk már fel (hash alapon).
"""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime

from ingestion.embedder import embed_and_store
from ingestion.file_readers import read_file

STATE_FILE = Path("data/processed_files.json")


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _file_hash(path: Path) -> str:
    """MD5 hash a fájl tartalmából — változás-detektáláshoz."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def scan_folder(
    folder: str | Path,
    force_reindex: bool = False,
    source_tag: str = "nas_munka",
) -> dict:
    """
    Rekurzívan végigmegy a mappán.
    Csak az új vagy megváltozott fájlokat dolgozza fel.
    Visszaad egy összefoglaló dict-et.
    """
    folder   = Path(folder)
    state    = _load_state()
    stats    = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}
    SUPPORTED = {".docx", ".pdf", ".xlsx", ".xls", ".txt", ".md"}

    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED]
    print(f"[Scanner] {len(files)} fájl található: {folder}")

    for file_path in files:
        key      = str(file_path.resolve())
        try:
            fhash    = _file_hash(file_path)
        except Exception as e:
            print(f"  [Hiba] Hash: {file_path.name}: {e}")
            stats["errors"] += 1
            continue

        if not force_reindex and state.get(key) == fhash:
            stats["skipped"] += 1
            continue

        is_update = key in state
        text = read_file(file_path)
        if not text or len(text.strip()) < 50:
            stats["skipped"] += 1
            continue

        metadata = {
            "source":       file_path.name,
            "source_path":  str(file_path),
            "source_tag":   source_tag,
            "file_type":    file_path.suffix.lower().lstrip("."),
            "indexed_at":   datetime.now().isoformat(),
        }

        try:
            n = embed_and_store(text, metadata, source_id=key)
            state[key] = fhash
            tag = "Frissítve" if is_update else "Betöltve"
            print(f"  [{tag}] {file_path.name}  ({n} chunk)")
            if is_update:
                stats["updated"] += 1
            else:
                stats["new"] += 1
        except Exception as e:
            print(f"  [Hiba] Embed: {file_path.name}: {e}")
            stats["errors"] += 1

    _save_state(state)
    print(f"\n[Scanner] Kész: {stats}")
    return stats
