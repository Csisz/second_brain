"""
scripts/cli.py
Parancssori eszköz — teszteléshez és kézi kezeléshez.

Használat:
  python scripts/cli.py ingest-folder ./data/sample_docs
  python scripts/cli.py ingest-file ./valami.pdf
  python scripts/cli.py sync-gmail --days 30
  python scripts/cli.py ask "Melyik ügyfelünknél volt VPN probléma?"
  python scripts/cli.py stats
"""
import sys
import os
from pathlib import Path

# projekt gyökér a Python path-ba
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

app    = typer.Typer(help="Second Brain CLI")
con    = Console()


@app.command()
def ingest_folder(
    folder: str = typer.Argument(..., help="Mappa elérési útja"),
    force: bool  = typer.Option(False, "--force", help="Újraindexelés kényszerítése"),
    tag: str     = typer.Option("nas_munka", "--tag", help="Forrás tag"),
):
    """Mappa rekurzív betöltése a tudásbázisba."""
    from ingestion.folder_scanner import scan_folder
    con.print(f"\n[bold cyan]📂 Mappa betöltése:[/] {folder}\n")
    stats = scan_folder(folder, force_reindex=force, source_tag=tag)
    t = Table(show_header=True)
    t.add_column("Státusz"); t.add_column("Darab", justify="right")
    t.add_row("✅ Új", str(stats["new"]))
    t.add_row("🔄 Frissítve", str(stats["updated"]))
    t.add_row("⏭️  Kihagyva", str(stats["skipped"]))
    t.add_row("❌ Hibás", str(stats["errors"]))
    con.print(t)


@app.command()
def ingest_file(
    file_path: str = typer.Argument(..., help="Fájl elérési útja"),
    tag: str = typer.Option("manual", "--tag"),
):
    """Egy fájl betöltése a tudásbázisba."""
    from ingestion.file_readers import read_file
    from ingestion.embedder import embed_and_store, ensure_collection
    from datetime import datetime

    p = Path(file_path)
    if not p.exists():
        con.print(f"[red]Fájl nem létezik:[/] {file_path}")
        raise typer.Exit(1)

    con.print(f"\n[bold cyan]📄 Fájl betöltése:[/] {p.name}")
    ensure_collection()
    text = read_file(p)
    if not text:
        con.print("[red]Nem olvasható fájlformátum.[/]")
        raise typer.Exit(1)

    metadata = {
        "source":     p.name,
        "source_tag": tag,
        "file_type":  p.suffix.lower().lstrip("."),
        "indexed_at": datetime.now().isoformat(),
    }
    n = embed_and_store(text, metadata)
    con.print(f"[green]✅ Betöltve:[/] {n} chunk  |  {p.name}")


@app.command()
def sync_gmail(
    days: int = typer.Option(90, "--days", help="Hány napra visszamenve"),
    max_emails: int = typer.Option(500, "--max"),
):
    """Gmail e-mailek szinkronizálása (első futtatáskor böngésző OAuth)."""
    from ingestion.gmail_reader import sync_gmail as _sync
    con.print(f"\n[bold cyan]📧 Gmail szinkronizálás:[/] utóbbi {days} nap\n")
    stats = _sync(days_back=days, max_emails=max_emails)
    con.print(f"\n[green]✅ Gmail kész:[/] {stats}")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Kérdés a tudásbázisnak"),
    top_k: int    = typer.Option(6, "--top-k"),
):
    """Kérdés feltevése — azonnali válasz a terminálban."""
    from query.engine import query as _query

    con.print(f"\n[bold yellow]❓ Kérdés:[/] {question}\n")
    with con.status("[cyan]Keresés és válaszgenerálás..."):
        result = _query(question, top_k=top_k)

    con.print(Panel(result.answer, title="🤖 Válasz", border_style="green"))

    if result.sources:
        con.print("\n[bold]📎 Felhasznált források:[/]")
        for src in result.sources:
            con.print(f"  • {src}")
    con.print(f"\n[dim]Modell: {result.model}  |  Chunk-ok: {result.chunks_used}[/]\n")


@app.command()
def stats():
    """Tudásbázis aktuális állapota."""
    from query.engine import get_collection_stats
    s = get_collection_stats()
    con.print(Panel(
        f"[cyan]Kollekció:[/] {s['collection']}\n"
        f"[cyan]Vektorok száma:[/] {s['total_vectors']}\n"
        f"[cyan]Státusz:[/] {s['status']}",
        title="📊 Tudásbázis statisztika",
        border_style="blue",
    ))


if __name__ == "__main__":
    app()
