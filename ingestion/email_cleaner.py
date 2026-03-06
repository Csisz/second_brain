"""
ingestion/email_cleaner.py
E-mail szöveg tisztítása betöltés előtt.
Szűri: mailto duplikációk, HTML maradványok, reply fejlécek, whitespace.
"""
from __future__ import annotations
import re


def clean_email_text(text: str) -> str:
    """
    Teljes e-mail szöveg tisztítása.
    Sorrendben alkalmazza az összes szűrőt.
    """
    if not text:
        return ""

    text = _remove_mailto_duplicates(text)
    text = _remove_html_tags(text)
    text = _remove_reply_headers(text)
    text = _remove_excessive_whitespace(text)
    text = _remove_email_signatures(text)
    text = _normalize_encoding_artifacts(text)

    return text.strip()


def _remove_mailto_duplicates(text: str) -> str:
    """
    Eltávolítja a <email@domain.hu<mailto:email@domain.hu>> duplikációkat.
    Csak a tiszta e-mail cím marad meg.
    
    Példa:
      <halai.helena@egis.hu<mailto:halai.helena@egis.hu>>
      → halai.helena@egis.hu
    """
    # <email<mailto:email>> minta
    text = re.sub(
        r'<([^<>\s]+@[^<>\s]+)<mailto:[^>]+>>',
        r'\1',
        text
    )
    # [email](mailto:email) markdown minta
    text = re.sub(
        r'\[([^\]]+@[^\]]+)\]\(mailto:[^\)]+\)',
        r'\1',
        text
    )
    # Önálló <mailto:email> tagek
    text = re.sub(r'<mailto:[^>]+>', '', text)
    return text


def _remove_html_tags(text: str) -> str:
    """
    HTML tagek és entitások eltávolítása.
    """
    # HTML tagek
    text = re.sub(r'<[^>]+>', ' ', text)
    # HTML entitások
    html_entities = {
        '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
        '&quot;': '"', '&apos;': "'", '&#39;': "'", '&ndash;': '–',
        '&mdash;': '—', '&hellip;': '...', '&rsquo;': "'",
        '&lsquo;': "'", '&rdquo;': '"', '&ldquo;': '"',
    }
    for entity, char in html_entities.items():
        text = text.replace(entity, char)
    # Numerikus entitások
    text = re.sub(r'&#\d+;', ' ', text)
    text = re.sub(r'&#x[0-9a-fA-F]+;', ' ', text)
    return text


def _remove_reply_headers(text: str) -> str:
    """
    Reply/forward fejlécek eltávolítása.
    
    Példák:
      On Mon, Jan 1, 2024 at 10:00 AM John wrote:
      -----Original Message-----
      Von: John Doe [mailto:...]
      Feladó: John Doe
    """
    patterns = [
        # Angol reply header
        r'On .{10,80} wrote:\s*',
        # Outlook separator
        r'-{3,}\s*Original Message\s*-{3,}.*',
        # Gmail quote marker sorok
        r'^>+.*$',
        # Sent from my iPhone/Android
        r'Sent from my (iPhone|Android|iPad|Samsung|mobile)',
        # Magyar fejlécek
        r'Feladó:.*\n',
        r'Elküldve:.*\n',
        r'Címzett:.*\n',
        r'Tárgy:.*\n',
        # Német fejlécek (ha van)
        r'Von:.*\n',
        r'Gesendet:.*\n',
        r'An:.*\n',
        r'Betreff:.*\n',
    ]
    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.MULTILINE | re.IGNORECASE)
    return text


def _remove_email_signatures(text: str) -> str:
    """
    E-mail aláírások eltávolítása.
    Az első '--' vagy '___' utáni rész általában aláírás.
    """
    # Standard email signature separator
    text = re.sub(r'\n--\s*\n.*', '', text, flags=re.DOTALL)
    text = re.sub(r'\n_{3,}\n.*', '', text, flags=re.DOTALL)
    # Confidentiality notices (hosszú jogi szövegek)
    text = re.sub(
        r'(This (email|message|communication) (is |may be )?confidential|'
        r'Ez az e-mail (bizalmas|titkos)).*',
        '',
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    return text


def _remove_excessive_whitespace(text: str) -> str:
    """
    Felesleges whitespace és üres sorok eltávolítása.
    Max 2 egymást követő üres sort enged meg.
    """
    # Több szóköz → egy szóköz
    text = re.sub(r'[ \t]+', ' ', text)
    # Több mint 2 üres sor → 2 üres sor
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Sor eleji/végi whitespace
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    return text


def _normalize_encoding_artifacts(text: str) -> str:
    """
    Kódolási hibák és egyéb artifactok javítása.
    """
    # Windows line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Null bytes
    text = text.replace('\x00', '')
    # Repeated punctuation (pl. .......... → ...)
    text = re.sub(r'\.{4,}', '...', text)
    text = re.sub(r'-{4,}', '---', text)
    text = re.sub(r'={4,}', '===', text)
    return text


def get_cleaning_stats(original: str, cleaned: str) -> dict:
    """
    Statisztika a tisztítás hatékonyságáról.
    """
    orig_len = len(original)
    clean_len = len(cleaned)
    reduction = (1 - clean_len / max(orig_len, 1)) * 100

    return {
        "original_chars": orig_len,
        "cleaned_chars": clean_len,
        "reduction_pct": round(reduction, 1),
        "mailto_removed": len(re.findall(r'<mailto:', original)),
        "html_tags_removed": len(re.findall(r'<[^>]+>', original)),
    }


# ─── Teszt ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_text = """
    From: <halai.helena@egis.hu<mailto:halai.helena@egis.hu>>
    To: <viktor.huszar@user.hu<mailto:viktor.huszar@user.hu>>
    CC: <Zsuzsa.Egyedi@4ig.hu<mailto:Zsuzsa.Egyedi@4ig.hu>>
    
    Hi Viktor,
    
    Please find the report attached.
    
    <b>Important:</b> The system will be &nbsp; down tomorrow.
    
    Best regards,
    Helena
    
    --
    Helena Halai | Egis IT
    Tel: +36 1 234 5678
    
    On Mon, Jan 1, 2024 at 10:00 AM Viktor wrote:
    > Can you send the report?
    
    This email is confidential and intended solely for the use of the individual.
    """

    cleaned = clean_email_text(test_text)
    stats = get_cleaning_stats(test_text, cleaned)

    print("=== EREDETI ===")
    print(test_text[:200])
    print("\n=== TISZTÍTOTT ===")
    print(cleaned)
    print("\n=== STATISZTIKA ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
