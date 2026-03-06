# 🧠 Second Brain — Személyes AI Tudásbázis

RAG-alapú személyes tudásbázis rendszer informatikai tanácsadóknak.  
**Stack:** Python · FastAPI · Qdrant · OpenAI Embeddings · Claude API · n8n · Telegram

---

## ⚡ Gyors indítás (5 perc)

### 1. Előfeltételek
- Python 3.11+
- Docker Desktop
- OpenAI API kulcs
- Anthropic API kulcs

### 2. Konfiguráció
```bash
cp .env.example .env
# Szerkeszd a .env fájlt: add meg az API kulcsokat
```

### 3. Qdrant indítása (vektoros adatbázis)
```bash
docker run -d -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  --name second_brain_qdrant \
  qdrant/qdrant
```

### 4. Python függőségek
```bash
pip install -r requirements.txt
```

### 5. Első dokumentumok betöltése (tesztadatok)
```bash
python scripts/cli.py ingest-folder ./data/sample_docs
```

### 6. Első kérdés!
```bash
python scripts/cli.py ask "Mi volt a VPN probléma megoldása?"
```

---

## 🚀 API szerver indítása

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: http://localhost:8000/docs

---

## 📋 CLI parancsok

| Parancs | Leírás |
|---------|--------|
| `python scripts/cli.py ingest-folder <mappa>` | Mappa rekurzív betöltése |
| `python scripts/cli.py ingest-file <fájl>` | Egy fájl betöltése |
| `python scripts/cli.py sync-gmail --days 90` | Gmail szinkronizálás |
| `python scripts/cli.py ask "<kérdés>"` | Kérdés a tudásbázisnak |
| `python scripts/cli.py stats` | Statisztikák |

---

## 🔌 API végpontok

| Végpont | Metódus | Leírás |
|---------|---------|--------|
| `GET /health` | GET | Státusz + statisztikák |
| `POST /query` | POST | Kérdés feltevése |
| `POST /ingest/text` | POST | Szöveg betöltése |
| `POST /ingest/file` | POST | Fájl feltöltése |
| `POST /ingest/scan` | POST | Mappa szkennelése |

### /query példa:
```json
POST http://localhost:8000/query
{
  "question": "Melyik ügyfelünknél volt Active Directory probléma?",
  "top_k": 6
}
```

---

## 📧 Gmail beállítása (Fázis 2)

1. [Google Cloud Console](https://console.cloud.google.com) → Új projekt
2. APIs & Services → Gmail API engedélyezése
3. OAuth 2.0 Client ID → Desktop app → letöltés → `credentials.json`
4. Első futtatás:
```bash
python scripts/cli.py sync-gmail --days 90
```
A böngésző megnyílik → bejelentkezés → `token.json` mentve → kész.

---

## 🤖 Telegram Bot beállítása (Fázis 3)

1. [@BotFather](https://t.me/BotFather) → `/newbot` → API token → `.env`-be
2. Saját Telegram User ID: [@userinfobot](https://t.me/userinfobot) → `.env`-be
3. n8n-be importáld: `n8n/telegram_bot_workflow.json`
4. n8n workflow aktiválás → Telegram botnak írva azonnal válaszol

---

## 🏗️ Projekt struktúra

```
second_brain/
├── api/
│   └── main.py              # FastAPI REST API
├── ingestion/
│   ├── embedder.py          # Chunking + OpenAI embedding + Qdrant
│   ├── file_readers.py      # .docx, .pdf, .xlsx, .txt olvasók
│   ├── folder_scanner.py    # Mappa rekurzív feldolgozás (delta sync)
│   └── gmail_reader.py      # Gmail OAuth2 szinkronizálás
├── query/
│   └── engine.py            # RAG lekérdező + Claude API
├── scripts/
│   └── cli.py               # Parancssori eszköz
├── n8n/
│   ├── gmail_ingestion_workflow.json  # n8n Gmail workflow
│   └── telegram_bot_workflow.json     # n8n Telegram bot
├── data/
│   ├── sample_docs/         # Tesztdokumentumok
│   └── processed_files.json # Delta sync állapot (auto-generált)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## 💡 Demo kérdések (ügyfeleknek)

```
"Melyik ügyfelünknél volt VMware/ESXi probléma?"
"Mi volt a döntés a backup rendszer felülvizsgálatán?"
"Mikor fejeződik be az Active Directory migráció?"
"Milyen VPN problémák voltak és mi a megoldás?"
"Összegezd a Bauer Logistics esetét."
```

---

## 📈 Skálázás (vállalati demó)

Ez a rendszer 1:1-ben skálázható:
- `data/sample_docs` → ügyfél SharePoint / NAS mappája  
- Gmail OAuth → ügyfél cég e-mail szervere  
- Telegram bot → Teams / Slack bot / beágyazott webchat  
- Lokális Docker → on-premise szerver  

**Projekt díj: €8.000 – €25.000**
