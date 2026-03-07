"""
ingestion/folder_scanner.py
NAS mappa rekurzív szkennelése és indexelése.

Funkciók:
- UNC path ellenőrzés (\\\\NAS\\...) — csak valóban elérhető fájlok
- Mappanév alapú source_tag meghatározás
- Fájl elérhetőség ellenőrzés (nem csak szimlink/sync placeholder)
- Hibás/nem olvasható fájlok kihagyása
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from datetime import datetime

from ingestion.embedder import embed_and_store
from ingestion.file_readers import read_file

# ─── Támogatott fájlkiterjesztések ───────────────────────────────────────────

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".docx", ".doc",
    ".xlsx", ".xls", ".pptx", ".ppt",
    ".csv", ".json", ".xml", 
    # ".html", ".htm",
    ".py", ".js", ".ts", ".java", ".cs",
    ".eml", ".msg",
}

# Kihagyandó mappák
SKIP_DIRS = {
    ".git", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", ".idea", ".vs", "bin", "obj",
    "$RECYCLE.BIN", "System Volume Information",
    "desktop.ini", "thumbs.db",
}

# Kihagyandó fájl prefixek/suffixek
SKIP_PATTERNS = {
    "~$",       # Office temp fájlok
    ".tmp",     # Temp fájlok
    ".lnk",     # Windows shortcut
    ".url",     # URL fájlok
}

# Maximális fájlméret (50 MB)
MAX_FILE_SIZE_MB = 50


def _is_file_accessible(path: Path) -> bool:
    """
    Ellenőrzi hogy a fájl ténylegesen elérhető-e.
    Fontos UNC / Synology NAS esetén ahol placeholder fájlok lehetnek.
    """
    try:
        # Szimlink ellenőrzés
        if path.is_symlink():
            return path.resolve().exists()

        # Méret ellenőrzés — 0 byte = placeholder/sync stub
        size = path.stat().st_size
        if size == 0:
            return False

        # Túl nagy fájl kihagyás
        if size > MAX_FILE_SIZE_MB * 1024 * 1024:
            print(f"  [SKIP] Túl nagy ({size // 1024 // 1024}MB): {path.name}")
            return False

        # Tényleges olvashatóság ellenőrzés — ez a kritikus teszt NAS esetén
        with open(path, "rb") as f:
            f.read(256)  # Próba olvasás
        return True

    except (OSError, PermissionError, IOError):
        return False


def _get_tag_from_path(file_path: Path, folder_root: Path, default_tag: str) -> str:
    """
    Mappanév alapján meghatározza a source_tag-et.
    Ha van explicit default_tag, azt használja.
    """
    if default_tag:
        return default_tag

    # Automatikus mappanév alapú tag
    path_lower = str(file_path).lower()
    auto_map = {
        "egis": "egis",
        "yettel": "yettel",
        "telenor_dk": "telenor_dk",
        "telenor": "telenor",
        "mvmi": "mvmi",
        "extended ecm": "extended_ecm",
        "extended_ecm": "extended_ecm",
        "oscript": "oscript",
        "vodafone": "4ig",
        "4ig": "4ig",
    }
    for keyword, tag in auto_map.items():
        if keyword in path_lower:
            return tag
    return "nas_egyeb"


def scan_folder(
    folder: str,
    force_reindex: bool = False,
    source_tag: str = "",
) -> dict:
    """
    Rekurzívan bejárja a mappát és indexeli a fájlokat.

    Args:
        folder: Az indexelendő mappa útvonala (UNC vagy lokális)
        force_reindex: Ha True, már indexelt fájlokat is újraindexeli
        source_tag: Explicit tag — ha üres, mappanévből automatikus

    Returns:
        Összefoglaló statisztika dict
    """
    folder_path = Path(folder)

    if not folder_path.exists():
        print(f"[Scan] HIBA: Mappa nem létezik vagy nem elérhető: {folder}")
        return {"error": f"Mappa nem elérhető: {folder}", "loaded": 0}

    if not folder_path.is_dir():
        print(f"[Scan] HIBA: Nem mappa: {folder}")
        return {"error": "Nem mappa", "loaded": 0}

    stats = {
        "folder": folder,
        "tag": source_tag or "auto",
        "loaded": 0,
        "skipped": 0,
        "errors": 0,
        "not_accessible": 0,
        "started_at": datetime.now().isoformat(),
    }

    print(f"\n[Scan] Indítás: {folder}")
    print(f"[Scan] Tag: {source_tag or 'auto (mappanév alapján)'}")
    print(f"[Scan] Force reindex: {force_reindex}")

    # Rekurzív bejárás
    all_files = []
    for root, dirs, files in os.walk(folder_path):
        # Kihagyandó mappák szűrése
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

        for filename in files:
            file_path = Path(root) / filename
            suffix = file_path.suffix.lower()

            # Kiterjesztés szűrés
            if suffix not in SUPPORTED_EXTENSIONS:
                continue

            # Temp/skip fájlok szűrése
            if any(filename.startswith(p) or filename.lower().endswith(p)
                   for p in SKIP_PATTERNS):
                continue

            all_files.append(file_path)

    total = len(all_files)
    print(f"[Scan] {total} fájl találva, ellenőrzés...")

    for i, file_path in enumerate(all_files, 1):
        try:
            # Elérhetőség ellenőrzés
            if not _is_file_accessible(file_path):
                stats["not_accessible"] += 1
                if i % 50 == 0:
                    print(f"  [{i}/{total}] {stats['loaded']} betöltve, {stats['not_accessible']} nem elérhető...")
                continue

            # Tag meghatározás
            tag = _get_tag_from_path(file_path, folder_path, source_tag)

            # Source ID a duplikátum elkerüléshez
            source_id = f"nas::{file_path}"

            # Szöveg kinyerése
            text = read_file(file_path)
            if not text or len(text.strip()) < 50:
                stats["skipped"] += 1
                continue

            # Metaadatok
            stat = file_path.stat()
            metadata = {
                "source":       str(file_path.name),
                "source_path":  str(file_path),
                "source_tag":   tag,
                "file_type":    file_path.suffix.lower().lstrip("."),
                "file_size":    stat.st_size,
                "indexed_at":   datetime.now().isoformat(),
            }

            # Indexelés
            n = embed_and_store(text, metadata, source_id=source_id)
            stats["loaded"] += 1

            if i % 10 == 0 or n > 5:
                print(f"  ✓ [{tag}] {file_path.name} ({n} chunk) [{i}/{total}]")

        except Exception as e:
            print(f"  ✗ Hiba: {file_path.name}: {e}")
            stats["errors"] += 1

        # Kis szünet NAS terhelés csökkentéséhez
        if i % 100 == 0:
            time.sleep(0.5)

    stats["finished_at"] = datetime.now().isoformat()
    print(f"\n[Scan] Kész: {stats}")
    return stats


# ─── Előre definiált NAS mappák ───────────────────────────────────────────────

NAS_FOLDERS = [
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\Egis",
        "tag": "egis",
    },
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\MVMI",
        "tag": "mvmi",
    },
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\Extended ECM",
        "tag": "extended_ecm",
    },
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\oscript",
        "tag": "oscript",
    },
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\Telenor",
        "tag": "telenor",
    },
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\Telenor_DK",
        "tag": "telenor_dk",
    },
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\Vodafone",
        "tag": "4ig",
    },
    {
        "path": r"\\HuKo\home\Drive\Backup\HVHP23\D\Munka\Yettel",
        "tag": "yettel",
    },
]


def scan_all_nas_folders(force_reindex: bool = False) -> dict:
    """
    Az összes előre definiált NAS mappát végigindexeli.
    Kihagyja az elérhetetlen mappákat.
    """
    total_stats = {"folders_scanned": 0, "folders_skipped": 0, "total_loaded": 0, "total_errors": 0}

    for folder_config in NAS_FOLDERS:
        path = folder_config["path"]
        tag = folder_config["tag"]

        if not Path(path).exists():
            print(f"\n[Scan] KIHAGYVA (nem elérhető): {path}")
            total_stats["folders_skipped"] += 1
            continue

        result = scan_folder(path, force_reindex=force_reindex, source_tag=tag)
        total_stats["folders_scanned"] += 1
        total_stats["total_loaded"] += result.get("loaded", 0)
        total_stats["total_errors"] += result.get("errors", 0)

    print(f"\n[Scan] Összesítés: {total_stats}")
    return total_stats
