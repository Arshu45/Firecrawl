# Promotion Intelligence POC

A retail promotion intelligence system for competitor monitoring, AI extraction, structured storage, dashboard-based insights, and conversational pricing analysis.

The current POC can:
- scrape competitor promotion pages
- extract structured offers with an LLM
- validate, normalize, and deduplicate offers
- load competitor and internal promotions into PostgreSQL
- expose a FastAPI-based chat backend
- show an insights dashboard and chatbot in Streamlit
- generate deterministic category-level recommendations through a backend tool

> **Current state:** Layers 0–8 are partially implemented end to end. The ingestion and structuring foundation is solid; recommendation, dashboard, and chat are functional; simulation, alerts, and scoring are still future work.

---

## Architecture

```text
Layer 8 — Conversational Agent      ✅ api/server.py + insights/agent.py
Layer 7 — Insights Dashboard        ✅ app.py
Layer 6 — API Layer                 ✅ api/server.py
Layer 5 — Recommendation Tool       ✅ insights/tools.py#get_recommendation
Layer 4 — Insights Tools            ✅ insights/tools.py

Layer 3 — PostgreSQL Database       ✅ database/loader.py
Layer 2 — Processing                ✅ processing/post_processor.py
Layer 1 — AI Extraction             ✅ extraction/groq_extractor.py
Layer 0 — Ingestion                 ✅ ingestion/firecrawl_fetcher.py

Internal MySQL Connector            ✅ connectors/mysql_fetcher.py + transformer.py
```

---

## Current Features

### Competitor Data Pipeline
- Scrapes configured competitor coupon/deal pages through Firecrawl
- Saves raw markdown snapshots for reuse
- Extracts structured promotion objects with Groq
- Validates with Pydantic before persistence
- Normalizes categories and deduplicates similar offers
- Loads clean results into PostgreSQL idempotently

### Internal Promotions Connector
- Pulls active internal promotions from MySQL
- Maps legacy fields through `config/internal_mapping.json`
- Loads into `internal_promotions` for side-by-side comparison with competitors

### Conversational Analysis
- FastAPI chat endpoint at `/api/chat`
- LangChain agent using PostgreSQL-backed tools
- Greeting bypass to avoid unnecessary tool/LLM usage
- Clarification flow when a query is too vague
- Per-session chat context via Streamlit-generated `session_id`
- Recent chat history is sent with each request and capped for token control
- Detailed backend terminal logging for request flow, tool selection, SQL activity, and final responses

### Insights Dashboard
- Streamlit dashboard and chat in one app
- KPIs for tracked competitors, categories, competitor offers, and internal offers
- Category-focused competitor snapshot
- Internal readiness view for the same category
- Recent competitor offers table
- Recent internal offers table

### Recommendation Logic
- Deterministic `get_recommendation(category, competitor)` tool
- Category-aware `get_active_offers(brand, category, limit)` tool
- Recommendation output includes urgency, discount-gap reasoning, tactic selection, and supporting offer examples
- Configurable limits for active offers and top competitors

---

## Project Structure

```text
AI_Promotional_POC/
├── app.py                          # Streamlit dashboard + chatbot UI
├── main.py                         # Master orchestrator + CLI
├── requirements.txt
├── .env                            # Secrets and runtime config (not committed)
│
├── api/
│   └── server.py                   # FastAPI chat backend
│
├── config/
│   ├── settings.py                 # Providers, app settings, constants
│   └── internal_mapping.json       # Internal MySQL → unified schema mapping
│
├── ingestion/
│   └── firecrawl_fetcher.py        # Layer 0: URL → clean Markdown
│
├── extraction/
│   ├── prompt_templates.py         # Centralized LLM prompts
│   └── groq_extractor.py           # Layer 1: Markdown → Offer objects
│
├── processing/
│   └── post_processor.py           # Layer 2: validate, normalize, deduplicate
│
├── connectors/
│   ├── mysql_fetcher.py            # Internal MySQL fetcher
│   └── transformer.py              # Internal data transformation layer
│
├── database/
│   ├── db_client.py                # PostgreSQL connection pool + query helpers
│   ├── loader.py                   # Idempotent load logic
│   └── schema.sql                  # Table definitions
│
├── insights/
│   ├── agent.py                    # Agent orchestration + session behavior
│   └── tools.py                    # SQL-backed insight and recommendation tools
│
├── output/                         # Timestamped raw/extracted/clean JSON artifacts
└── tests/
```

---

## Tech Stack

| Layer | Tool |
|-------|------|
| Scraping | `firecrawl-py` |
| Extraction LLM | `groq` |
| Agent LLM | `langchain-groq` |
| Agent Orchestration | `langchain` |
| Validation | `pydantic` |
| Deduplication | `rapidfuzz` |
| Retries | `tenacity` |
| API | `fastapi` + `uvicorn` |
| UI | `streamlit` |
| Database | `psycopg2-binary` + PostgreSQL |
| Internal Connector | `pymysql` |

---

## Environment Setup

Create a `.env` file in the project root:

```env
FIRECRAWL_API_KEY=your_firecrawl_api_key_here
GROQ_API_KEY=your_groq_api_key_here
DATABASE_URL=postgresql://user:password@localhost:5432/promo_db

CLIENT_BRAND=YourBrandName         # e.g. Westside, Fabindia, H&M — drives all UI labels and agent persona
DEFAULT_TOP_COMPETITORS_LIMIT=5
DEFAULT_ACTIVE_OFFERS_LIMIT=5
CHAT_HISTORY_WINDOW=4
MAX_HISTORY_TURNS=6
API_URL=http://127.0.0.1:8000/api/chat

# PostgreSQL Pool
DB_MIN_CONN=1
DB_MAX_CONN=10

# MySQL Connector Credentials
MYSQL_HOST=172.27.133.173
MYSQL_PORT=3306
MYSQL_USER=readonly_user
MYSQL_PASS=cybage@123
MYSQL_DB=fashion_retail

# Processing & LLM OVERRIDES (optional)
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_TEMPERATURE=0
GROQ_MAX_TOKENS=2000
CHUNK_SIZE=5000
CHUNK_OVERLAP=200
FUZZY_THRESHOLD=85
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the database schema:

```bash
psql -d promo_db -f database/schema.sql
```

---

## How to Run

### 1. Run the data pipeline

Full pipeline for all configured providers:

```bash
python main.py
```

Specific providers only:

```bash
python main.py --providers Myntra Nykaa
```

Skip DB load:

```bash
python main.py --skip-db
```

Re-run extraction on saved markdown:

```bash
python main.py --extract-only output/raw_markdown_Myntra_2026-04-07.json
```

Load an already-clean JSON file into PostgreSQL:

```bash
python main.py --load-only output/promotions_clean_Myntra_2026-04-07.json
```

Sync internal promotions from MySQL:

```bash
python main.py --sync-internal
```

### 2. Run the API backend

```bash
uvicorn api.server:app --reload
```

### 3. Run the Streamlit app

```bash
streamlit run app.py
```

The app includes two tabs:
- `Dashboard` for visual insights
- `Chat` for natural language analysis

---

## Output Files

Each pipeline run produces timestamped files in `output/`:

| File | Contents |
|------|----------|
| `raw_markdown_{Provider}_{ts}.json` | Raw scraped markdown |
| `promotions_raw_{Provider}_{ts}.json` | Extracted offers before cleanup |
| `promotions_clean_{Provider}_{ts}.json` | Final validated + deduplicated offers |

---

## How It Works

### Layer 0 — Ingestion
- Uses Firecrawl to scrape competitor pages as markdown
- Scrolls pages to trigger lazy-loaded offer content
- Excludes obvious noise like nav, footer, ads, and popups
- Saves raw markdown to `output/`

### Layer 1 — AI Extraction
- Chunks markdown before sending it to Groq
- Extracts structured promotions as JSON
- Validates each record with the `Offer` Pydantic model
- Drops malformed or invalid records

Extracted fields:

```text
offer_title, description, brand, category, promo_type,
discount_min, discount_max, flat_value, min_purchase,
coupon_code, user_type, valid_until
```

### Layer 2 — Processing
- field validation
- category normalization
- fuzzy deduplication
- null cleanup (`"NULL"` → real nulls)
- `valid_until` normalization from relative/text values to ISO dates where possible
- basic promo-type correction for obvious extraction mistakes
- output shaping into a clean provider payload

### Layer 3 — Database
- loads competitor data into `competitors` and `promotions`
- loads internal data into `internal_promotions`
- keeps competitor loads idempotent
- uses PostgreSQL connection pooling
- stores `valid_until` as a SQL `DATE`

### Layer 4–5 — Insights and Recommendations

Current tools in `insights/tools.py`:
- `get_category_trends(category)`
- `get_top_competitors(category, limit)`
- `get_active_offers(brand, category=None, limit=...)`
- `get_recommendation(category, competitor)`

### Layer 6–8 — API, Dashboard, and Chat
- FastAPI backend exposes the chat endpoint
- Streamlit shows both dashboard and chatbot
- Chat agent receives recent capped history on each request
- Logging shows request flow, tool usage, SQL activity, and output previews in the backend terminal

---

## Chat Behavior

The chat agent is designed to be safer and more scoped than the initial version:

- greetings do not trigger tools
- vague analytical questions trigger a clarification request
- recent history is replayed into each request with a cap to control token growth
- category-specific questions should keep tool scope aligned to that category
- recommendation-style questions should route through the deterministic recommendation tool
- category-aware brand offer retrieval prevents mixing unrelated categories in one answer

Example prompts:

```text
Hi
What is Myntra doing in Footwear?
Show me Myntra's active offers in Footwear
What is Myntra doing in Footwear, and what should we do?
What category trends do we see in Beauty?
```

---

## Insights Dashboard

The dashboard currently supports:
- latest scrape status
- market KPIs
- category-focused competitor comparison
- internal data availability check
- recent competitor and internal offer tables

This is intended to complement the chatbot, not replace it.

---

## Configured Providers

Edit `config/settings.py` to change providers:

```python
COMPETITOR_SITES = {
    "Myntra": "https://www.grabon.in/myntra-coupons/",
    "Nykaa": "https://www.grabon.in/nykaa-coupons/",
}
```

---

## Known Gaps

These are still open and worth prioritizing next:
- internal recommendations depend on `internal_promotions` being populated
- recommendation logic is still discount-gap based; it is not yet margin- or cost-aware
- competitiveness scoring is not built yet
- alerts are not built yet
- impact simulation is not built yet
- test coverage is still minimal

---

## Design Principles

- prompts are centralized
- validation happens before DB load
- the data pipeline is modular
- recommendation logic is moving toward deterministic tooling instead of pure LLM advice
- the backend is heavily logged for observability

---

## Suggested Smoke Test

1. Run `python main.py --skip-db`
2. Confirm JSON artifacts appear in `output/`
3. Run `python main.py`
4. Start `uvicorn api.server:app --reload`
5. Start `streamlit run app.py`
6. Open the dashboard and verify KPIs/tables populate
7. Test chat prompts:
   - `Hi`
   - `What is Myntra doing in Footwear?`
   - `What is Myntra doing in Footwear, and what should we do?`
