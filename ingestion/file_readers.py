"""
ingestion/file_readers.py
Fájl formátum olvasók: .docx, .pdf, .xlsx
"""
import io
from pathlib import Path


def read_docx(path: str | Path) -> str:
    from docx import Document
    doc = Document(str(path))
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    # Táblázatok szövege is
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(
                cell.text.strip() for cell in row.cells if cell.text.strip()
            )
            if row_text:
                parts.append(row_text)
    return "\n".join(parts)


def read_pdf(path: str | Path) -> str:
    import PyPDF2
    text_parts = []
    with open(str(path), "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            t = page.extract_text()
            if t and t.strip():
                text_parts.append(t.strip())
    return "\n".join(text_parts)


def read_xlsx(path: str | Path) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    parts = []
    for sheet in wb.worksheets:
        parts.append(f"[Sheet: {sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            row_text = " | ".join(str(c) for c in row if c is not None and str(c).strip())
            if row_text:
                parts.append(row_text)
    return "\n".join(parts)


def read_txt(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


READERS = {
    ".docx": read_docx,
    ".pdf":  read_pdf,
    ".xlsx": read_xlsx,
    ".xls":  read_xlsx,
    ".txt":  read_txt,
    ".md":   read_txt,
}


def read_file(path: str | Path) -> str | None:
    """Visszaadja a fájl szöveges tartalmát, vagy None-t ha nem támogatott."""
    suffix = Path(path).suffix.lower()
    reader = READERS.get(suffix)
    if not reader:
        return None
    try:
        return reader(path)
    except Exception as e:
        print(f"[Olvasás hiba] {path}: {e}")
        return None
