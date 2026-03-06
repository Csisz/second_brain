"""
ingestion/gmail_reader.py
Gmail e-mailek beolvasása OAuth2 segítségével.
Domain alapú source_tag meghatározás + AI kategorizálás ismeretlen domaineknél.
"""
import os
import re
import base64
from datetime import datetime, timedelta
from pathlib import Path

from ingestion.embedder import embed_and_store
from ingestion.email_cleaner import clean_email_text

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE  = os.getenv("GMAIL_TOKEN_FILE", "token.json")

# ─── Domain → tag mapping ────────────────────────────────────────────────────

DOMAIN_TAG_MAP = {
    # Egis
    "egis.hu": "egis",
    # Yettel
    "yettel.hu": "yettel",
    # Telenor HU
    "telenor.hu": "telenor",
    # Telenor DK
    "telenor.dk": "telenor_dk",
    # 4iG csoport
    "4ig.hu": "4ig",
    "vodafone.hu": "4ig",
    "one.hu": "4ig",
    "vodafone.com": "4ig",
    # MVMI
    "mvmi.hu": "mvmi",
}

# AI kategorizáláshoz — tárgy/tartalom kulcsszavak
KEYWORD_TAG_MAP = {
    "egis": ["egis", "pharma", "gyógyszer", "ecm", "opentext"],
    "yettel": ["yettel", "mobilnet", "előfizető"],
    "telenor": ["telenor", "network", "nettwork"],
    "4ig": ["vodafone", "4ig", "one.hu"],
    "mvmi": ["mvmi", "vállalati mobil"],
    "extended_ecm": ["extended ecm", "xecm", "content server", "otcs"],
    "oscript": ["oscript", "livelink", "ot script"],
}


def _extract_domain(email_address: str) -> str | None:
    """Kinyeri a domain részt egy e-mail címből."""
    match = re.search(r'@([\w.-]+)', email_address.lower())
    return match.group(1) if match else None


def _get_tag_from_addresses(from_addr: str, to_addr: str, cc_addr: str = "") -> str | None:
    """Domain alapján meghatározza a source_tag-et."""
    all_addresses = f"{from_addr} {to_addr} {cc_addr}"
    domains = re.findall(r'@([\w.-]+)', all_addresses.lower())

    for domain in domains:
        # Pontos egyezés
        if domain in DOMAIN_TAG_MAP:
            return DOMAIN_TAG_MAP[domain]
        # Aldomain egyezés (pl. mail.egis.hu → egis)
        for key, tag in DOMAIN_TAG_MAP.items():
            if domain.endswith(f".{key}") or domain == key:
                return tag
    return None


def _get_tag_from_content(subject: str, body: str) -> str:
    """Kulcsszó alapú kategorizálás ha a domain nem ismert."""
    text = f"{subject} {body[:500]}".lower()
    for tag, keywords in KEYWORD_TAG_MAP.items():
        for kw in keywords:
            if kw in text:
                return tag
    return "gmail"  # fallback


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
    for part in msg_payload.get("parts", []):
        result = _decode_body(part)
        if result:
            return result
    return ""


def _parse_message(raw_msg: dict) -> dict | None:
    """Egy Gmail message dict-ből kinyeri a metaadatokat és meghatározza a tag-et."""
    headers = {h["name"]: h["value"] for h in raw_msg["payload"]["headers"]}
    subject = headers.get("Subject", "(nincs tárgy)")
    sender  = headers.get("From", "")
    date    = headers.get("Date", "")
    to      = headers.get("To", "")
    cc      = headers.get("Cc", "")
    body    = _decode_body(raw_msg["payload"])

    # Szöveg tisztítása
    body = clean_email_text(body)

    if not body or len(body.strip()) < 30:
        return None

    # Tag meghatározás: domain → kulcsszó → fallback
    tag = _get_tag_from_addresses(sender, to, cc)
    if not tag:
        tag = _get_tag_from_content(subject, body)

    full_text = f"Tárgy: {subject}\nFeladó: {sender}\nCímzett: {to}\nDátum: {date}\n\n{body}"

    return {
        "text":       full_text,
        "source":     f"Gmail: {subject[:80]}",
        "subject":    subject,
        "sender":     sender,
        "to":         to,
        "date":       date,
        "source_tag": tag,
        "file_type":  "email",
        "indexed_at": datetime.now().isoformat(),
    }


def sync_gmail(
    days_back: int = 90,
    max_emails: int = 500,
    label: str = "INBOX",
    recipient: str = "viktor.huszar@user.hu",
) -> dict:
    """
    Lekéri az utóbbi days_back nap e-mailjeit és betölti a KB-ba.
    Domain alapján automatikusan meghatározza a source_tag-et.
    """
    service = _get_service()
    stats   = {"loaded": 0, "skipped": 0, "errors": 0, "tags": {}}

    after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
    query = f"after:{after_date} to:{recipient} -category:promotions -category:social"

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
            tag = parsed["source_tag"]
            stats["tags"][tag] = stats["tags"].get(tag, 0) + 1
            print(f"  ✓ [{tag}] {parsed['subject'][:60]} ({n} chunk)")
            stats["loaded"] += 1
        except Exception as e:
            print(f"  ✗ Hiba: {msg_ref['id']}: {e}")
            stats["errors"] += 1

    print(f"\n[Gmail] Kész: {stats}")
    return stats
