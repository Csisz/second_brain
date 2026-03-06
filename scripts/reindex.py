"""
scripts/reindex.py
Teljes újraindexelés script.

Lépések:
1. Qdrant kollekció törlése és újralétrehozása
2. NAS mappák indexelése (csak elérhetők)
3. Gmail szinkronizálás domain-alapú tag-gelel

Használat:
    python scripts/reindex.py                    # Teljes újraindexelés
    python scripts/reindex.py --only-gmail       # Csak Gmail
    python scripts/reindex.py --only-nas         # Csak NAS
    python scripts/reindex.py --dry-run          # Csak listázás, nem indexel
    python scripts/reindex.py --days 365         # Gmail: utóbbi 365 nap
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Projekt gyökér hozzáadása a path-hoz
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


def clear_collection():
    """Törli és újralétrehozza a Qdrant kollekciót."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams

    client = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333)),
    )
    collection = os.getenv("QDRANT_COLLECTION", "second_brain")
    vector_size = int(os.getenv("VECTOR_SIZE", 1536))

    # Kollekció törlése ha létezik
    try:
        client.delete_collection(collection)
        print(f"[Reset] Kollekció törölve: {collection}")
    except Exception:
        print(f"[Reset] Kollekció nem létezett: {collection}")

    # Újralétrehozás
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    print(f"[Reset] Kollekció létrehozva: {collection} (dim={vector_size})")


def check_nas_folders():
    """Ellenőrzi melyik NAS mappa elérhető."""
    from ingestion.folder_scanner import NAS_FOLDERS
    print("\n[NAS] Mappa elérhetőség ellenőrzés:")
    available = []
    for f in NAS_FOLDERS:
        path = Path(f["path"])
        exists = path.exists()
        status = "✓ ELÉRHETŐ" if exists else "✗ NEM ELÉRHETŐ"
        print(f"  [{f['tag']:15}] {status}: {f['path']}")
        if exists:
            available.append(f)
    print(f"\n  {len(available)}/{len(NAS_FOLDERS)} mappa elérhető")
    return available


def run_nas_indexing(dry_run: bool = False, force: bool = False):
    """NAS mappák indexelése."""
    available = check_nas_folders()
    if not available:
        print("[NAS] Nincs elérhető mappa, kihagyás.")
        return

    if dry_run:
        print("[NAS] Dry-run mód — nem indexelünk.")
        return

    from ingestion.folder_scanner import scan_folder
    total = {"loaded": 0, "skipped": 0, "errors": 0, "not_accessible": 0}

    for folder_config in available:
        print(f"\n{'='*60}")
        print(f"[NAS] Indexelés: {folder_config['tag']} → {folder_config['path']}")
        print(f"{'='*60}")
        result = scan_folder(
            folder=folder_config["path"],
            force_reindex=force,
            source_tag=folder_config["tag"],
        )
        for k in total:
            total[k] += result.get(k, 0)

    print(f"\n[NAS] Végeredmény: {total}")


def run_gmail_indexing(days: int = 365, dry_run: bool = False):
    """Gmail szinkronizálás."""
    recipient = os.getenv("GMAIL_RECIPIENT", "viktor.huszar@user.hu")
    print(f"\n[Gmail] Szinkronizálás: utóbbi {days} nap, címzett: {recipient}")

    if dry_run:
        print("[Gmail] Dry-run mód — nem indexelünk.")
        return

    from ingestion.gmail_reader import sync_gmail
    result = sync_gmail(days_back=days, recipient=recipient)

    print(f"\n[Gmail] Tag bontás:")
    for tag, count in sorted(result.get("tags", {}).items(), key=lambda x: -x[1]):
        print(f"  {tag:20} {count} e-mail")


def main():
    parser = argparse.ArgumentParser(description="Second Brain — Teljes újraindexelés")
    parser.add_argument("--only-gmail", action="store_true", help="Csak Gmail indexelés")
    parser.add_argument("--only-nas", action="store_true", help="Csak NAS indexelés")
    parser.add_argument("--dry-run", action="store_true", help="Csak listázás, nem indexel")
    parser.add_argument("--days", type=int, default=365, help="Gmail: utóbbi N nap (default: 365)")
    parser.add_argument("--force", action="store_true", help="Már indexelt fájlok újraindexelése")
    parser.add_argument("--no-reset", action="store_true", help="Ne törölje a meglévő adatokat")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Second Brain — Újraindexelés")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # 1. Reset (hacsak --no-reset nincs megadva)
    if not args.no_reset and not args.dry_run:
        print("\n[1/3] Adatbázis reset...")
        confirm = input("  FIGYELEM: Minden adat törlődik! Folytatja? (igen/nem): ")
        if confirm.lower() != "igen":
            print("  Megszakítva.")
            return
        clear_collection()
    elif args.dry_run:
        print("\n[DRY-RUN] Adatbázis NEM törlődik.")

    # 2. NAS indexelés
    if not args.only_gmail:
        print("\n[2/3] NAS mappák indexelése...")
        run_nas_indexing(dry_run=args.dry_run, force=args.force)

    # 3. Gmail indexelés
    if not args.only_nas:
        print("\n[3/3] Gmail szinkronizálás...")
        run_gmail_indexing(days=args.days, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"  Kész! {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
