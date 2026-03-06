"""
discord_bot/bot.py
Discord bot — Second Brain tudásbázis lekérdező.

Használat:
  python discord_bot/bot.py

Parancsok Discordon:
  !ask <kérdés>     — Kérdés a tudásbázisnak
  !stats            — Tudásbázis statisztika
  !ingest           — Utolsó szinkronizálás státusza
  !help             — Parancsok listája
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands

# ─── Konfiguráció ────────────────────────────────────────────────────────────

TOKEN          = os.getenv("DISCORD_BOT_TOKEN")
ALLOWED_USER   = int(os.getenv("DISCORD_ALLOWED_USER_ID", "0"))
PREFIX         = "!"

if not TOKEN:
    print("[Hiba] DISCORD_BOT_TOKEN nincs beállítva a .env fájlban!")
    sys.exit(1)

# ─── Bot inicializálás ───────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


# ─── Auth helper ─────────────────────────────────────────────────────────────

def is_allowed(ctx) -> bool:
    """Csak az engedélyezett user küldhet parancsokat."""
    return ALLOWED_USER == 0 or ctx.author.id == ALLOWED_USER


# ─── Events ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"[Discord] Bot bejelentkezve: {bot.user} (ID: {bot.user.id})")
    print(f"[Discord] Engedélyezett user ID: {ALLOWED_USER}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="a tudásbázisodat 🧠"
        )
    )


# ─── Parancsok ───────────────────────────────────────────────────────────────

@bot.command(name="help")
async def help_cmd(ctx):
    """Parancsok listája."""
    if not is_allowed(ctx):
        return

    embed = discord.Embed(
        title="🧠 Second Brain Bot",
        description="Személyes AI tudásbázis asszisztens",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="!ask <kérdés>",
        value="Kérdés a tudásbázisnak\nPl: `!ask Mi volt a VPN probléma megoldása?`",
        inline=False
    )
    embed.add_field(
        name="!stats",
        value="Tudásbázis statisztika — hány dokumentum van betöltve",
        inline=False
    )
    embed.add_field(
        name="!sync",
        value="Gmail szinkronizálás indítása (utóbbi 7 nap)",
        inline=False
    )
    embed.add_field(
        name="!scan <mappa>",
        value="NAS mappa betöltése\nPl: `!scan \\\\HuKo\\home\\Drive\\Munka\\_teszt`",
        inline=False
    )
    embed.set_footer(text="Second Brain v1.0 — RAG + Claude API")
    await ctx.send(embed=embed)


@bot.command(name="ask")
async def ask_cmd(ctx, *, question: str):
    """Kérdés a tudásbázisnak."""
    if not is_allowed(ctx):
        await ctx.send("⛔ Hozzáférés megtagadva.")
        return

    if not question.strip():
        await ctx.send("❓ Adj meg egy kérdést! Pl: `!ask Mi volt a VPN probléma?`")
        return

    # "Gépel..." jelzés
    async with ctx.typing():
        try:
            from query.engine import query as _query
            result = _query(question)

            # Válasz embed összerakása
            embed = discord.Embed(
                title=f"❓ {question[:100]}",
                description=result.answer[:4000],  # Discord limit 4096 karakter
                color=discord.Color.green()
            )

            if result.sources:
                sources_text = "\n".join(f"• {s[:100]}" for s in result.sources[:5])
                embed.add_field(
                    name="📎 Felhasznált források",
                    value=sources_text,
                    inline=False
                )

            embed.set_footer(
                text=f"Modell: {result.model} | Chunk-ok: {result.chunks_used}"
            )
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Hiba történt: `{str(e)[:200]}`")


@bot.command(name="stats")
async def stats_cmd(ctx):
    """Tudásbázis statisztika."""
    if not is_allowed(ctx):
        return

    async with ctx.typing():
        try:
            from query.engine import get_collection_stats
            s = get_collection_stats()

            embed = discord.Embed(
                title="📊 Tudásbázis statisztika",
                color=discord.Color.blue()
            )
            embed.add_field(name="Kollekció", value=s["collection"], inline=True)
            embed.add_field(name="Vektorok", value=str(s["total_vectors"]), inline=True)
            embed.add_field(name="Státusz", value=s["status"], inline=True)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Hiba: `{str(e)[:200]}`")


@bot.command(name="sync")
async def sync_cmd(ctx, days: int = 7):
    """Gmail szinkronizálás indítása."""
    if not is_allowed(ctx):
        return

    await ctx.send(f"📧 Gmail szinkronizálás indul... (utóbbi {days} nap)")

    async with ctx.typing():
        try:
            import asyncio
            from ingestion.gmail_reader import sync_gmail

            # Háttérben futtatjuk hogy ne blokkoljuk a botot
            loop = asyncio.get_event_loop()
            stats = await loop.run_in_executor(
                None,
                lambda: sync_gmail(days_back=days)
            )

            embed = discord.Embed(
                title="✅ Gmail szinkronizálás kész",
                color=discord.Color.green()
            )
            embed.add_field(name="Betöltve", value=str(stats["loaded"]), inline=True)
            embed.add_field(name="Kihagyva", value=str(stats["skipped"]), inline=True)
            embed.add_field(name="Hibás", value=str(stats["errors"]), inline=True)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Szinkronizálás hiba: `{str(e)[:200]}`")


@bot.command(name="scan")
async def scan_cmd(ctx, *, folder: str):
    """NAS mappa betöltése."""
    if not is_allowed(ctx):
        return

    await ctx.send(f"📂 Mappa szkennelés indul: `{folder}`")

    async with ctx.typing():
        try:
            import asyncio
            from ingestion.folder_scanner import scan_folder

            loop = asyncio.get_event_loop()
            stats = await loop.run_in_executor(
                None,
                lambda: scan_folder(folder, source_tag="nas_munka")
            )

            embed = discord.Embed(
                title="✅ Mappa betöltés kész",
                color=discord.Color.green()
            )
            embed.add_field(name="Új", value=str(stats["new"]), inline=True)
            embed.add_field(name="Frissítve", value=str(stats["updated"]), inline=True)
            embed.add_field(name="Kihagyva", value=str(stats["skipped"]), inline=True)
            embed.add_field(name="Hibás", value=str(stats["errors"]), inline=True)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Scan hiba: `{str(e)[:200]}`")


# ─── Indítás ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[Discord] Bot indul...")
    bot.run(TOKEN)