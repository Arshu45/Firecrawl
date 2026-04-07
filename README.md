# Retail Promotion Intelligence

A **Decision Intelligence System** for retail brands to monitor competitor promotions, extract AI-structured offers, and generate actionable pricing recommendations — complete with a Streamlit dashboard and an AI chatbot.

Configurable for any retail brand — plug in your own competitors, categories, and pricing data.

> Built with Firecrawl · Groq LLaMA 3.3 70B · PostgreSQL · Streamlit

---

## What This System Does

1. **Scrapes** competitor coupon pages (GrabOn) as clean Markdown via Firecrawl
2. **Extracts** every promotional offer into structured JSON using Groq LLM (Pydantic-validated)
3. **Cleans** the data — validates, normalises categories, deduplicates with fuzzy matching
4. **Stores** offers in PostgreSQL with idempotent upserts (safe to re-run)
5. **Analyses** the market with 5 fixed SQL queries + LLM-generated narrative summaries
6. **Recommends** pricing actions via a deterministic rule engine explained by the LLM
7. **Chats** with you via an intent-routing AI assistant (exactly 2 LLM calls per query)
8. **Visualises** everything across 5 Streamlit screens

---

## Tech Stack

| Concern | Tool |
|---------|------|
| Web scraping | `firecrawl-py` |
| LLM / AI | `groq` — LLaMA 3.3 70B (`llama-3.3-70b-versatile`) |
| Data validation | `pydantic` v2 |
| Fuzzy dedup | `rapidfuzz` |
| Database | PostgreSQL + `psycopg2-binary` |
| Data wrangling | `pandas` |
| Dashboard / UI | `streamlit` |
| Retry logic | `tenacity` |
| HTTP client | `httpx` |
| Config | `python-dotenv` |
| Language | Python 3.11+ |

---

## Architecture

```
Layer 7 — Streamlit Dashboard (5 screens)
Layer 6 — AI Chatbot (intent router + tool executor)
Layer 5 — Recommendation Engine (rules + LLM explanation)
Layer 4 — Insights Engine (5 fixed SQL queries + LLM narration)
Layer 3 — PostgreSQL Database
Layer 2 — Processing (validate, normalise, rapidfuzz dedup)
Layer 1 — AI Extraction (Groq → Pydantic-validated JSON)
Layer 0 — Ingestion (Firecrawl → clean Markdown)
```

**Key design rules:**
- No LangChain, no vector DB, no RAG
- All business logic is deterministic — LLM only narrates and routes
- All SQL queries are fixed and parameterised — no dynamic SQL from user input
- Every LLM call is wrapped in `tenacity` (3 retries, exponential backoff)
- Pipeline is idempotent — running twice on the same date never duplicates DB rows

---

## Project Structure

```
promo_pipeline/
│
├── main.py                          # Master CLI orchestrator
├── requirements.txt
├── .env.example                     # Copy this to .env and fill in keys
│
├── config/
│   └── settings.py                  # API keys, models, COMPETITOR_SITES, CATEGORY_MAP
│
├── ingestion/
│   └── firecrawl_fetcher.py         # Layer 0: URL → clean Markdown (tenacity retries)
│
├── extraction/
│   ├── prompt_templates.py          # All LLM prompts (single source of truth)
│   └── groq_extractor.py            # Layer 1: Markdown → Pydantic Offer objects
│
├── processing/
│   └── post_processor.py            # Layer 2: validate + normalise + rapidfuzz dedup
│
├── database/
│   ├── schema.sql                   # Table definitions (run once)
│   ├── db_client.py                 # Connection pool + query helpers
│   └── loader.py                    # Idempotent upsert to PostgreSQL
│
├── insights/
│   └── insights_engine.py           # Layer 4: 5 fixed SQL queries + LLM narration
│
├── recommendations/
│   └── recommendation_engine.py     # Layer 5: rule engine + LLM explanation
│
├── chatbot/
│   └── chat_engine.py               # Layer 6: intent router + tool executor
│
├── ui/
│   └── app.py                       # Layer 7: 5-screen Streamlit dashboard
│
└── output/                          # Timestamped JSON outputs (gitignored)
```

---

## Project Setup Guide

### 1. Prerequisites

- Python 3.11+
- PostgreSQL running locally (or a remote instance)
- A [Firecrawl API key](https://firecrawl.dev)
- A [Groq API key](https://console.groq.com)

### 2. Clone & Create Virtual Environment

```bash
# From the repo root
python -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
```

### 3. Install Dependencies

```bash
cd promo_pipeline
pip install -r requirements.txt
```

### 4. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
FIRECRAWL_API_KEY=your_firecrawl_api_key_here
GROQ_API_KEY=your_groq_api_key_here
DATABASE_URL=postgresql://postgres:password@localhost:5432/promo_db
```

### 5. Set Up the Database

```bash
# Create the database
createdb promo_db

# Apply the schema (creates tables + seed data)
psql -d promo_db -f database/schema.sql
```

Verify it worked:

```bash
psql -d promo_db -c "SELECT * FROM internal_pricing;"
```

---

## How To Run

All commands should be run from inside `promo_pipeline/` with your virtualenv active.

### Run the Full Pipeline

Fetch → Extract → Process → Load to DB:

```bash
python main.py
```

### Select Specific Competitors

```bash
python main.py --providers Myntra Nykaa
```

Available providers: `Myntra`, `Nykaa` (configured in `config/settings.py`)

### Dry Run (No DB Write)

```bash
python main.py --providers Myntra --skip-db
```

### Fetch Markdown Only

Scrapes pages and saves `output/raw_markdown_*.json` without calling Groq:

```bash
python main.py --fetch-only
```

### Extract from Saved Markdown

Runs Groq extraction + processing + DB load on an already-fetched file:

```bash
python main.py --extract-only output/raw_markdown_Myntra_20260406_120000.json
```

### Launch the Dashboard

```bash
streamlit run ui/app.py
```

Opens at `http://localhost:8501`

---

## Dashboard Screens

| Screen | What It Shows |
|--------|--------------|
| **📋 Promotions Table** | Live filtered table of competitor offers. Highlights rows with discount > 60%. CSV export. |
| **📊 Market Insights** | Bar charts (avg discount by category, top 5 competitors). LLM narrative. Coupon availability. User targeting breakdown. |
| **💡 Recommendations** | Enter your category, discount, and margin → get a colour-coded URGENT/MEDIUM/LOW/HOLD card with SITUATION / RECOMMENDATION / REASONING. |
| **⚙️ Run Pipeline** | Run the full pipeline from the UI with live step-by-step logs and a summary on completion. |
| **🤖 AI Assistant** | Chat interface. Routes your question to the right engine automatically. Examples shown on load. |

---

## Offer Schema (Pydantic)

Every extracted offer is validated against:

```python
class Offer(BaseModel):
    offer_title  : str
    description  : Optional[str]
    brand        : Optional[str]
    category     : Optional[str]          # Fashion, Footwear, Beauty, Electronics, Home, Sports, Other
    promo_type   : str                     # percentage, flat, bogo, bundle, free_delivery, other
    discount_min : Optional[float]
    discount_max : Optional[float]
    flat_value   : Optional[float]
    min_purchase : Optional[float]
    coupon_code  : Optional[str]
    user_type    : str                     # new, existing, all
    valid_until  : Optional[str]
```

---

## Processing Rules

After extraction, the post-processor:

1. **Validates** — drops offers with no title or discount > 100%
2. **Fixes** — swaps `discount_min`/`discount_max` if inverted
3. **Normalises categories** — e.g. `"skincare"` → `"Beauty"`, `"mobiles"` → `"Electronics"`
4. **Deduplicates** — uses `rapidfuzz` fuzzy matching (ratio ≥ 85) on title + same discount_min; increments `source_count` on merge

---

## Recommendation Engine Logic

A pure deterministic rule engine runs first — no LLM involved:

| Market Gap | Action | Urgency |
|-----------|--------|---------|
| > 20% | URGENT_MATCH | 🔴 High |
| > 10% | BUNDLE_OFFER | 🟠 Medium |
| > 0% | MONITOR | 🟢 Low |
| ≤ 0% | HOLD | ⚪ None |

The LLM then explains the decision in **SITUATION / RECOMMENDATION / REASONING** format.

---

## Output Files

Each pipeline run writes timestamped files to `output/`:

| File | Contents |
|------|----------|
| `raw_markdown_{provider}_{ts}.json` | Raw Firecrawl markdown per URL |
| `promotions_raw_{provider}_{ts}.json` | Pydantic-validated offers before processing |
| `promotions_clean_{provider}_{ts}.json` | Final validated, normalised, deduped offers |

---

## Notes

- The pipeline is **modular** — you can run any layer independently
- The `output/` folder is gitignored
- Old directories (`fetcher/`, `extractor/`, `deduplicator/`) are legacy and unused
- `tests/test_fetcher.py` exists but is minimal — test coverage is a future task
