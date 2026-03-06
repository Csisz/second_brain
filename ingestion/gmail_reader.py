"""
ingestion/gmail_reader.py
Gmail e-mailek beolvasása OAuth2 segítségével.

Első futtatáskor megnyitja a böngészőt az OAuth hitelesítéshez.
Utána a token.json-ban tárolja a tokent — nem kell újra belépni.

Beállítás:
1. Google Cloud Console → Új projekt → Gmail API engedélyezése
2. OAuth 2.0 Client ID létrehozása (Desktop app típus)
3. credentials.json letöltése → projekt gyökerébe másolás
"""
import os
import base64
import email as email_lib
from datetime import datetime, timedelta
from pathlib import Path

from ingestion.embedder import embed_and_store

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE  = os.getenv("GMAIL_TOKEN_FILE", "token.json")


def _get_service():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        Path(TOKEN_FILE).write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _decode_body(msg_payload) -> str:
    """Rekurzívan kinyeri a plain/text részt."""
    if msg_payload.get("mimeType") == "text/plain":
        data = msg_payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    parts = msg_payload.get("parts", [])
    for part in parts:
        result = _decode_body(part)
        if result:
            return result
    return ""


def _parse_message(raw_msg: dict) -> dict | None:
    """Egy Gmail message dict-ből kinyeri a metaadatokat és a szöveget."""
    headers = {h["name"]: h["value"] for h in raw_msg["payload"]["headers"]}
    subject = headers.get("Subject", "(nincs tárgy)")
    sender  = headers.get("From", "")
    date    = headers.get("Date", "")
    body    = _decode_body(raw_msg["payload"])

    if not body or len(body.strip()) < 30:
        return None

    # Kombináljuk a metaadatokat a szöveggel a jobb kereshetőségért
    full_text = f"Tárgy: {subject}\nFeladó: {sender}\nDátum: {date}\n\n{body}"

    return {
        "text":     full_text,
        "source":   f"Gmail: {subject[:80]}",
        "subject":  subject,
        "sender":   sender,
        "date":     date,
        "source_tag": "gmail",
        "file_type": "email",
        "indexed_at": datetime.now().isoformat(),
    }


def sync_gmail(
    days_back: int = 90,
    max_emails: int = 500,
    label: str = "INBOX",
) -> dict:
    """
    Lekéri az utóbbi `days_back` nap e-mailjeit és betölti a KB-ba.
    Visszaad egy összefoglaló dict-et.
    """
    service = _get_service()
    stats   = {"loaded": 0, "skipped": 0, "errors": 0}

    after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    query      = f"after:{after_date} -category:promotions -category:social"

    print(f"[Gmail] Lekérés: utóbbi {days_back} nap, max {max_emails} e-mail...")
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_emails, labelIds=[label]
    ).execute()

    messages = results.get("messages", [])
    print(f"[Gmail] {len(messages)} e-mail találva.")

    for msg_ref in messages:
        try:
            raw = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="full"
            ).execute()
            parsed = _parse_message(raw)
            if not parsed:
                stats["skipped"] += 1
                continue

            n = embed_and_store(
                parsed["text"],
                {k: v for k, v in parsed.items() if k != "text"},
                source_id=f"gmail::{msg_ref['id']}",
            )
            print(f"  [Gmail] Betöltve: {parsed['subject'][:60]}  ({n} chunk)")
            stats["loaded"] += 1
        except Exception as e:
            print(f"  [Gmail hiba] {msg_ref['id']}: {e}")
            stats["errors"] += 1

    print(f"\n[Gmail] Kész: {stats}")
    return stats
