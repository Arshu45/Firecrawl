# Promotion Intelligence POC

A retail competitor promotion monitoring pipeline. Scrapes coupon/deal websites, extracts structured promotional offers using AI, and produces clean validated JSON — ready for database ingestion and business insights.

> **Current state:** Layers 0–3 implemented (Ingestion → Extraction → Processing → DB Load). Layer 4+ (Insights, Recommendations, UI) in progress.

---

## Architecture

```
Layer 8 — AI Chatbot               (planned)
Layer 7 — Streamlit Dashboard      (planned)
Layer 5 — Recommendation Engine    (planned)
Layer 4 — Insights Engine          (planned)
Layer 3 — PostgreSQL Database      ✅ database/loader.py
Layer 2 — Processing               ✅ processing/post_processor.py
Layer 1 — AI Extraction            ✅ extraction/groq_extractor.py
Layer 0 — Ingestion                ✅ ingestion/firecrawl_fetcher.py
```

---

## Project Structure

```
AI_Promotional_POC/
├── main.py                          # Master orchestrator + CLI
├── requirements.txt
├── .env                             # API keys (not committed)
│
├── config/
│   └── settings.py                  # COMPETITOR_SITES, CATEGORY_MAP, VALID_*, all constants
│
├── ingestion/
│   └── firecrawl_fetcher.py         # Layer 0: URL → clean Markdown (Firecrawl)
│
├── extraction/
│   ├── prompt_templates.py          # All LLM prompts in one place
│   └── groq_extractor.py            # Layer 1: Markdown → validated Offer objects (Groq)
│
├── processing/
│   └── post_processor.py            # Layer 2: validate, normalise, deduplicate
│
├── database/
│   ├── db_client.py                 # Layer 3: psycopg2 connection pool
│   ├── loader.py                    # Layer 3: idempotent upsert
│   └── schema.sql                   # Layer 3: table definitions
│
├── output/                          # Timestamped JSON outputs (gitignored)
└── tests/
```

---

## Tech Stack

| Layer | Tool |
|-------|------|
| Scraping | `firecrawl-py` |
| AI / LLM | `groq` — LLaMA 3.3 70B |
| Validation | `pydantic` |
| Deduplication | `rapidfuzz` |
| Retries | `tenacity` |
| Config | `python-dotenv` |
| DB (Layer 3+) | `psycopg2-binary` + PostgreSQL |
| UI (Layer 7+) | `streamlit` |

---

## Environment Setup

Create a `.env` file in the project root:

```env
FIRECRAWL_API_KEY=your_firecrawl_api_key_here
GROQ_API_KEY=your_groq_api_key_here
DATABASE_URL=postgresql://user:password@localhost:5432/promo_db  # needed from Layer 3 onwards
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## How to Run (Layers 0–2)

### Full pipeline (Layers 0-3 for all providers)
```bash
python main.py
```

### Specific providers only (with DB load)
```bash
python main.py --providers Myntra Nykaa
```

### Run pipeline but skip the DB load (Layers 0-2 only)
```bash
python main.py --skip-db
```

### Layer 1-3: AI extraction on already-scraped data
Saves Firecrawl API credits — reuses a saved `raw_markdown_*.json` file:
```bash
python main.py --extract-only output/raw_markdown_Myntra_2026-04-07.json
```

### Layer 3: Load existing clean JSON into DB
Bypasses both APIs to load processed data natively into the DB:
```bash
python main.py --load-only output/promotions_clean_Myntra_2026-04-07.json
```

---

## Output Files

Each pipeline run produces timestamped files in `output/`:

| File | Contents |
|------|----------|
| `raw_markdown_{Provider}_{ts}.json` | Raw Markdown scraped from Firecrawl |
| `promotions_raw_{Provider}_{ts}.json` | Offers extracted by Groq (pre-cleanup) |
| `promotions_clean_{Provider}_{ts}.json` | Final validated + deduplicated offers |

---

## How It Works — Layer by Layer

### Layer 0 — Ingestion (`ingestion/firecrawl_fetcher.py`)

- Scrapes each configured URL using the Firecrawl SDK
- Scrolls the page 12× (2s each) to trigger lazy-loaded coupon cards
- Strips noise: nav, footer, ads, popups, sidebars
- Wraps in `tenacity` retry — 3 attempts, 5s wait
- Auto-saves `output/raw_markdown_{Provider}_{ts}.json`

Output shape per page:
```json
{
  "provider"    : "Myntra",
  "url"         : "https://www.grabon.in/myntra-coupons/",
  "scraped_at"  : "2026-04-07T14:20:00",
  "scraped_date": "2026-04-07",
  "markdown"    : "...",
  "char_count"  : 42300
}
```

### Layer 1 — AI Extraction (`extraction/groq_extractor.py`)

- Splits Markdown into **3,000-char chunks with 200-char overlap** (prevents cutting mid-offer)
- Sends each chunk to Groq LLM (`llama-3.3-70b-versatile`, temperature=0)
- Validates every extracted offer with a **Pydantic `Offer` model** — drops invalid records
- Wraps each Groq call in `tenacity` — 3 retries with exponential backoff
- All prompts live in `extraction/prompt_templates.py` (never inlined)

Offer schema:
```
offer_title, description, brand, category, promo_type,
discount_min, discount_max, flat_value, min_purchase,
coupon_code, user_type, valid_until
```

### Layer 2 — Processing (`processing/post_processor.py`)

Three sequential steps:

1. **Field Validation** — drops offers missing `offer_title`, drops hallucinated discounts (>100%), swaps `discount_min`/`discount_max` if inverted, applies defaults for `user_type` and `promo_type`
2. **Category Normalisation** — maps synonyms to canonical names using `CATEGORY_MAP` (e.g. `"sportswear"` → `"Sports"`, `"cosmetics"` → `"Beauty"`)
3. **Fuzzy Deduplication** — uses `rapidfuzz` with 85% title similarity threshold + same `discount_min` to identify duplicates; merges richer fields; tracks `source_count`

### Layer 3 — Database (`database/loader.py`)

- Thin `psycopg2` client wrapper using `SimpleConnectionPool` and `RealDictCursor`
- **Fully idempotent**: Uses `ON CONFLICT DO NOTHING` for competitors and checks `(offer_title, competitor_id, scraped_date)` to avoid duplicates
- Separates `promotions` tracking from `internal_pricing` mapping for margins

---

## Configured Providers

Edit `config/settings.py` to add or change providers:

```python
COMPETITOR_SITES = {
    "Myntra"  : "https://www.grabon.in/myntra-coupons/",
    "Ajio"    : "https://www.grabon.in/ajio-coupons/",
    "Nykaa"   : "https://www.grabon.in/nykaa-coupons/",
    "Flipkart": "https://www.grabon.in/flipkart-coupons/",
}
```

---

## Design Principles

- **No LangChain, no vector DB, no RAG** — simple, auditable Python only
- **Deterministic business logic** — LLM only touches extraction and narration
- **Idempotent pipeline** — running twice for the same date will not produce duplicates (enforced at DB layer)
- **All prompts centralised** in `extraction/prompt_templates.py`
- **Pydantic validation** before any data touches the database
