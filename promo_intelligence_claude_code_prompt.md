# Promotion Intelligence POC — Claude Code Master Build Prompt

> Paste this entire prompt into Claude Code. It will build the system layer by layer, feature by feature.

---

## CONTEXT & MENTAL MODEL

You are building a **Promotion Intelligence POC** for a retail brand (Westside) to monitor competitor promotions (Myntra, Ajio, etc.) and generate actionable pricing recommendations.

This is a **Decision Intelligence System**, not a scraping project. The business value is at the top — recommendations explained in plain language. Everything below is infrastructure.

```
Architecture:
Layer 8 — AI Chatbot (Streamlit chat interface)
Layer 7 — Streamlit Dashboard (4 screens)
Layer 5 — Recommendation Engine (rules + LLM)
Layer 4 — Insights Engine (SQL + LLM narration)
Layer 3 — PostgreSQL Database
Layer 2 — Processing Layer (dedup, validate, normalize)
Layer 1 — AI Extraction (Groq → structured JSON)
Layer 0 — Ingestion (Firecrawl → markdown)
```

**Key architectural decisions — never deviate from these:**
- NO LangChain. NO LangGraph. NO vector DB. NO RAG.
- NO NL→SQL generation. Use fixed parameterised SQL queries only.
- LLM touches data at exactly 2 points: intent routing + narration/explanation.
- All business logic (rules, math, aggregations) stays deterministic.
- Two LLM calls per chatbot query max. Full auditability.

---

## TECH STACK

```
Ingestion      : firecrawl-py
AI/LLM         : groq (LLaMA 3.3 70B)
Processing     : rapidfuzz, pydantic
Database       : PostgreSQL + psycopg2-binary
Data           : pandas
UI             : streamlit
Utilities      : python-dotenv, tenacity, httpx
```

No other packages unless absolutely necessary.

---

## PROJECT STRUCTURE TO CREATE

```
promo_pipeline/
│
├── main.py                        # Master orchestrator
├── .env.example                   # API key template
├── requirements.txt
├── README.md
│
├── config/
│   └── settings.py                # Sites, models, thresholds, category maps
│
├── ingestion/
│   └── firecrawl_fetcher.py       # Layer 0: URL → clean markdown
│
├── extraction/
│   ├── groq_extractor.py          # Layer 1: markdown → structured JSON
│   └── prompt_templates.py        # ALL prompts in one file
│
├── processing/
│   └── post_processor.py          # Layer 2: dedup, validate, normalize
│
├── database/
│   ├── schema.sql                 # Table definitions
│   ├── db_client.py               # Connection + query runner
│   └── loader.py                  # Clean JSON → PostgreSQL upsert
│
├── insights/
│   └── insights_engine.py         # Layer 4: fixed SQL + LLM narration
│
├── recommendations/
│   └── recommendation_engine.py   # Layer 5: rule engine + LLM explanation
│
├── chatbot/
│   └── chat_engine.py             # Layer 8: intent router + tool executor
│
├── ui/
│   └── app.py                     # Streamlit: all 5 screens including chat
│
└── output/                        # Timestamped JSON outputs (gitignored)
```

---

## BUILD INSTRUCTIONS — LAYER BY LAYER

Build each layer completely before moving to the next. After each layer, confirm it works in isolation before proceeding.

---

### LAYER 0 — INGESTION (`ingestion/firecrawl_fetcher.py`)

Build a Firecrawl-based fetcher with the following behaviour:

```python
# fetch_promotions(url: str, provider: str) -> dict
# Returns: {
#   "provider": str,
#   "url": str,
#   "scraped_at": ISO timestamp,
#   "markdown": str,
#   "char_count": int
# }
```

Requirements:
- Use `firecrawl-py` SDK
- Enable scroll actions to handle lazy-loaded content (scroll 5 times, 500px each)
- Set timeout to 30 seconds
- Wrap in `tenacity` retry: 3 attempts, 5 second wait, on any exception
- Log: fetching started, char count retrieved, any errors
- Save raw markdown to `output/raw_markdown_{provider}_{timestamp}.json`

Target URLs to configure in `config/settings.py`:
```python
COMPETITOR_SITES = {
    "Myntra"  : "https://www.grabon.in/myntra-coupons/",
    "Ajio"    : "https://www.grabon.in/ajio-coupons/",
    "Nykaa"   : "https://www.grabon.in/nykaa-coupons/",
    "Flipkart": "https://www.grabon.in/flipkart-coupons/",
}
```

---

### LAYER 1 — AI EXTRACTION (`extraction/groq_extractor.py` + `prompt_templates.py`)

Build the Groq-based extractor that converts markdown → structured JSON offers.

**Chunking strategy:**
- Split markdown into chunks of max 3000 characters
- Overlap chunks by 200 characters to avoid cutting offers mid-way
- Process each chunk independently, merge results

**Output schema per offer (use Pydantic):**
```python
class Offer(BaseModel):
    offer_title   : str
    description   : Optional[str]
    brand         : Optional[str]
    category      : Optional[str]
    promo_type    : str  # "percentage", "flat", "bogo", "bundle", "free_delivery"
    discount_min  : Optional[float]
    discount_max  : Optional[float]
    flat_value    : Optional[float]
    min_purchase  : Optional[float]
    coupon_code   : Optional[str]
    user_type     : str  # "new", "existing", "all"
    valid_until   : Optional[str]
```

**Extraction prompt (in `prompt_templates.py`):**
```
EXTRACTION_PROMPT = """
You are a retail promotion data extractor.
Extract ALL promotional offers from the markdown below.

Return a JSON array of offers. Each offer must have:
- offer_title: exact title of the offer
- promo_type: one of [percentage, flat, bogo, bundle, free_delivery, other]
- discount_min: lowest discount % mentioned (number only, no % sign)
- discount_max: highest discount % mentioned (number only, no % sign)
- flat_value: flat rupee discount if mentioned
- min_purchase: minimum purchase amount if mentioned
- coupon_code: exact coupon code if mentioned, else null
- user_type: "new" if only for new users, "existing" if for existing, "all" otherwise
- category: product category (Fashion, Footwear, Beauty, Electronics, Home, Sports, Other)
- brand: brand name if mentioned

Rules:
- Extract EVERY offer. Do not summarise or skip.
- If discount range is "up to 80%", set discount_max=80, discount_min=null
- If exact discount is "50% off", set both min and max to 50
- Return ONLY the JSON array. No preamble. No explanation.

Markdown:
{markdown_chunk}
"""
```

**Groq call config:**
- Model: `llama-3.3-70b-versatile`
- Temperature: 0 (deterministic extraction)
- Max tokens: 2000 per chunk
- Wrap in tenacity: 3 retries, exponential backoff
- Parse response with `json.loads()`, validate each item with Pydantic
- Drop any offer that fails Pydantic validation — log it, don't crash

**Output:**
- Save to `output/promotions_raw_{provider}_{timestamp}.json`
- Return list of validated `Offer` objects

---

### LAYER 2 — PROCESSING (`processing/post_processor.py`)

Build the post-processor that makes data trustworthy before DB insertion.

**Step 1 — Field Validation (drop bad records):**
```python
# Drop if: no offer_title
# Drop if: discount_min > 100 (hallucination)
# Drop if: discount_max > 100 (hallucination)
# Fix if:  discount_min > discount_max → swap them
# Default: user_type = "all" if missing or null
# Default: promo_type = "other" if missing
```

**Step 2 — Category Normalisation:**
```python
# In config/settings.py:
CATEGORY_MAP = {
    "sportswear"    : "Sports",
    "sportwear"     : "Sports",
    "apparels"      : "Fashion",
    "apparel"       : "Fashion",
    "women shoes"   : "Footwear",
    "men shoes"     : "Footwear",
    "footwears"     : "Footwear",
    "makeup"        : "Beauty",
    "cosmetics"     : "Beauty",
    "skincare"      : "Beauty",
    "mobiles"       : "Electronics",
    "smartphones"   : "Electronics",
    "home decor"    : "Home",
    "furniture"     : "Home",
}
# Case-insensitive matching. If no match, keep original.
```

**Step 3 — Cross-site Deduplication:**
```python
# Two offers are duplicates if:
# same provider + fuzzy title match >= 85% + same discount_min
# Use rapidfuzz.fuzz.ratio for title comparison
# Keep first occurrence, add source_count field (default 1, increment on dedup)
```

**Step 4 — Output:**
```python
# Returns: {
#   "provider"     : str,
#   "source_url"   : str,
#   "scraped_date" : "YYYY-MM-DD",
#   "total_raw"    : int,
#   "total_clean"  : int,
#   "dropped"      : int,
#   "offers"       : [list of clean validated offers]
# }
# Save to output/promotions_clean_{provider}_{timestamp}.json
```

---

### LAYER 3 — DATABASE (`database/`)

**`schema.sql` — create these tables:**

```sql
CREATE TABLE IF NOT EXISTS competitors (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(100) UNIQUE NOT NULL,
    source_url   TEXT,
    added_date   DATE DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS promotions (
    id            SERIAL PRIMARY KEY,
    competitor_id INT REFERENCES competitors(id),
    offer_title   TEXT NOT NULL,
    description   TEXT,
    brand         VARCHAR(100),
    category      VARCHAR(50),
    promo_type    VARCHAR(50),
    discount_min  NUMERIC(5,2),
    discount_max  NUMERIC(5,2),
    flat_value    NUMERIC(10,2),
    min_purchase  NUMERIC(10,2),
    coupon_code   VARCHAR(50),
    user_type     VARCHAR(20) DEFAULT 'all',
    source_count  INT DEFAULT 1,
    source_url    TEXT,
    scraped_date  DATE DEFAULT CURRENT_DATE,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS internal_pricing (
    id        SERIAL PRIMARY KEY,
    category  VARCHAR(50) UNIQUE NOT NULL,
    our_discount  NUMERIC(5,2) DEFAULT 0,
    margin    NUMERIC(5,2),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_promotions_competitor ON promotions(competitor_id);
CREATE INDEX IF NOT EXISTS idx_promotions_category ON promotions(category);
CREATE INDEX IF NOT EXISTS idx_promotions_scraped_date ON promotions(scraped_date);
```

**`db_client.py`:**
```python
# DBClient class with:
# - __init__: reads DATABASE_URL from .env, creates connection pool
# - execute(query, params) → list of dicts
# - execute_one(query, params) → single dict or None
# - execute_write(query, params) → rowcount
# - close()
# Use psycopg2.extras.RealDictCursor so rows come back as dicts
# Connection pooling: psycopg2.pool.SimpleConnectionPool(1, 10)
```

**`loader.py`:**
```python
# load_promotions(clean_data: dict) → {"inserted": int, "skipped": int}
#
# Logic:
# 1. Upsert competitor: INSERT INTO competitors(name, source_url)
#    ON CONFLICT(name) DO NOTHING — return id
# 2. For each offer:
#    Check if (offer_title, competitor_id, scraped_date) already exists
#    If yes: skip (idempotent — re-running pipeline is safe)
#    If no:  INSERT into promotions
# 3. Return counts
```

**`db_client.py` reads from `.env`:**
```
DATABASE_URL=postgresql://user:password@localhost:5432/promo_db
```

---

### LAYER 4 — INSIGHTS ENGINE (`insights/insights_engine.py`)

All SQL queries are **fixed and parameterised**. No SQL generation.

**Implement these 5 query functions:**

```python
def avg_discount_by_category(days: int = 7) -> list[dict]:
    # Returns: [{"category": str, "avg_discount": float, "offer_count": int}]

def top_competitors_in_category(category: str, days: int = 7) -> list[dict]:
    # Returns: [{"competitor": str, "avg_discount": float, "offer_count": int}]
    # Limit 5

def coupon_availability_by_provider(days: int = 7) -> list[dict]:
    # Returns: [{"competitor": str, "with_coupon": int, "total": int, "pct": float}]

def user_type_targeting(days: int = 7) -> list[dict]:
    # Returns: [{"competitor": str, "user_type": str, "count": int}]

def recent_offers(provider: str = None, category: str = None,
                  days: int = 7, limit: int = 20) -> list[dict]:
    # Filterable offer list for the promotions table screen
    # Build WHERE clause dynamically from non-None params
```

**LLM Narration (one function):**
```python
def generate_narrative(query_name: str, data: list[dict], context: dict) -> str:
    # Calls Groq with this prompt structure:
    # "You are a retail pricing analyst for an Indian fashion brand.
    #  Given this market data about {context}, write a 3-sentence summary.
    #  Be specific — mention brand names and exact numbers.
    #  Use ₹ for rupees. Keep it under 80 words. No bullet points."
    # Returns: narrative string
```

**Public interface:**
```python
def run_insight(insight_type: str, params: dict) -> dict:
    # Routes to correct query function
    # Appends LLM narrative
    # Returns: {"data": list, "narrative": str, "insight_type": str}
```

---

### LAYER 5 — RECOMMENDATION ENGINE (`recommendations/recommendation_engine.py`)

**Two-layer approach — deterministic rules first, LLM explains second.**

**Rule engine:**
```python
def get_rule_decision(market_avg: float, our_discount: float, our_margin: float) -> dict:
    gap = market_avg - our_discount
    
    if gap > 20:
        action   = "URGENT_MATCH"
        urgency  = "high"
        label    = "Urgent: Match market within 48 hours"
    elif gap > 10:
        action   = "BUNDLE_OFFER"
        urgency  = "medium"
        label    = "Consider a bundle offer to stay competitive"
    elif gap > 0:
        action   = "MONITOR"
        urgency  = "low"
        label    = "Monitor — within acceptable range"
    else:
        action   = "HOLD"
        urgency  = "none"
        label    = "We are competitive — maintain position"
    
    # Estimate margin impact
    if action == "URGENT_MATCH":
        suggested_discount = market_avg
    elif action == "BUNDLE_OFFER":
        suggested_discount = our_discount + (gap * 0.6)
    else:
        suggested_discount = our_discount
    
    margin_impact = our_margin - (suggested_discount - our_discount)
    
    return {
        "action"             : action,
        "urgency"            : urgency,
        "label"              : label,
        "gap"                : round(gap, 1),
        "suggested_discount" : round(suggested_discount, 1),
        "margin_impact"      : round(margin_impact, 1)
    }
```

**LLM Explanation prompt (in `prompt_templates.py`):**
```
RECOMMENDATION_PROMPT = """
You are a retail pricing strategist for Westside, an Indian fashion brand.

Market context:
- Category: {category}
- Top competitor: {top_competitor} at {top_discount}% average discount
- Market average discount: {market_avg}%
- Our current discount: {our_discount}%
- Our margin in this category: {our_margin}%
- Rule decision: {rule_label}

Write a recommendation in exactly this format — 3 labelled parts:

SITUATION:
[1 sentence — what the market is doing right now. Use numbers.]

RECOMMENDATION:
[1 sentence — exactly what Westside should do. Be specific.]

REASONING:
[1 sentence — why this protects margin. Use ₹ per unit if margin data allows.]

Tone: confident, direct, no hedging. Use Indian retail context.
"""
```

**Public interface:**
```python
def get_recommendation(category: str, our_discount: float, our_margin: float) -> dict:
    # 1. Fetch market data for category from DB (top competitor + avg discount)
    # 2. Run rule engine
    # 3. Generate LLM explanation
    # Returns: {
    #   "category"     : str,
    #   "market_data"  : dict,
    #   "rule"         : dict,
    #   "explanation"  : {"situation": str, "recommendation": str, "reasoning": str}
    # }
    # Parse the SITUATION/RECOMMENDATION/REASONING from LLM output into separate fields
```

---

### LAYER 6 — CHATBOT ENGINE (`chatbot/chat_engine.py`)

**This is the glue layer. No new LLM logic — just routing to existing engines.**

**Intent routing prompt (in `prompt_templates.py`):**
```
INTENT_ROUTER_PROMPT = """
You are an intent router for a retail promotion intelligence system.

Available tools:
1. search_promotions — use when asked about specific offers, what a competitor is running, coupon codes
2. get_insights — use when asked about market trends, category summaries, averages, comparisons
3. get_recommendation — use when asked what Westside should do, how to respond to a competitor
4. answer_direct — use when the question can be answered from conversation context alone

User question: {question}

Return ONLY a JSON object:
{
  "tool": "<tool_name>",
  "params": {
    "provider"   : "<name or null>",
    "category"   : "<category or null>",
    "days"       : <7 or 30>,
    "our_discount": <number or null>,
    "our_margin"  : <number or null>
  },
  "reasoning": "<one line why this tool>"
}
"""
```

**Response generation prompt (in `prompt_templates.py`):**
```
RESPONSE_PROMPT = """
You are Westside's Promotion Intelligence Assistant.
You help the pricing and marketing team understand competitor promotions
and decide what Westside should do.

Conversation so far:
{history}

User asked: {question}

Data retrieved:
{tool_output}

Write a helpful, specific response. Use numbers. Mention brand names.
Use ₹ for rupees. If it is a recommendation, use SITUATION/RECOMMENDATION/REASONING format.
Keep it under 150 words. Be direct. No filler phrases.
"""
```

**Main chat function:**
```python
def chat(question: str, history: list[dict]) -> dict:
    # Step 1: Route intent (LLM call #1)
    # Step 2: Execute tool (deterministic — calls existing engines)
    # Step 3: Generate response (LLM call #2)
    # Step 4: Return {"response": str, "tool_used": str, "data": dict}
    
    # history format: [{"role": "user"|"assistant", "content": str}]
    # Keep last 6 turns of history for context (avoid token bloat)
```

---

### LAYER 7 — STREAMLIT UI (`ui/app.py`)

Build a single-file Streamlit app with 5 screens via sidebar navigation.

**Design requirements:**
- Dark theme (`st.set_page_config(layout="wide")`)
- Professional, data-dense layout — this is for business analysts
- Use `st.sidebar` for navigation
- Page title: "Westside Promotion Intelligence"
- Sidebar logo/header: "🏷️ Promo Intel"

**Screen 1 — Promotions Table**
```
Title: "Live Competitor Promotions"
Filters row: [Provider multiselect] [Category multiselect] [User Type select] [Days slider 1-30]
Table: offer_title | brand | category | promo_type | discount_min | discount_max | coupon_code | user_type | scraped_date
- Highlight rows where discount_max > 60 in amber
- Show record count below table
- Download button: "Export CSV"
```

**Screen 2 — Market Insights**
```
Title: "Market Intelligence"
Top row: [Category select] [Days slider]
Left column (60%):
  - Bar chart: Average discount by category (horizontal bars, sorted desc)
  - Bar chart: Top 5 competitors in selected category
Right column (40%):
  - "Market Narrative" card with LLM-generated summary
  - Coupon code availability table (% of offers with codes by provider)
  - New vs existing user targeting breakdown
```

**Screen 3 — Recommendation**
```
Title: "Pricing Recommendation Engine"
Input panel:
  - Category select (from DB)
  - "Our current discount" number input (0-100)
  - "Our margin in this category %" number input (0-100)
  - [Get Recommendation] button

Output card (shown after button click):
  - Urgency badge (colour-coded: red/amber/green)
  - SITUATION block
  - RECOMMENDATION block  
  - REASONING block
  - Margin impact metric: "Suggested discount: X% | Estimated margin: Y%"
```

**Screen 4 — Run Pipeline**
```
Title: "Data Pipeline Control"
Left panel:
  - Checkboxes for each competitor in COMPETITOR_SITES
  - [▶ Run Pipeline] button
Right panel:
  - Live log area using st.empty() updated during run
  - Shows: Fetching → Extracting → Processing → Loading → Done
  - Summary metrics after completion: offers fetched, inserted, skipped
```

**Screen 5 — AI Assistant**
```
Title: "Ask Promo Intel AI"
Subtitle: "Ask anything about competitor promotions or what Westside should do"

Example questions shown on load:
  - "What is Myntra doing in footwear this week?"
  - "Which category has the highest market discount right now?"
  - "Ajio launched 70% off ethnic wear. What should we do?"
  - "Show me all offers with coupon codes"

Chat interface:
  - st.chat_message for each turn
  - st.chat_input at bottom
  - st.session_state.messages for history
  - Show "tool used: X" in small text below each assistant response
  - [Clear Chat] button in sidebar when on this screen
```

---

### MASTER ORCHESTRATOR (`main.py`)

```python
# CLI entry point — run full pipeline for specified providers
# Usage: python main.py --providers Myntra Ajio --skip-db

import argparse

def run_pipeline(providers: list[str], skip_db: bool = False):
    results = {}
    for provider in providers:
        # 1. Fetch markdown (Layer 0)
        # 2. Extract offers (Layer 1)
        # 3. Process/clean (Layer 2)
        # 4. Load to DB (Layer 3) — unless skip_db
        # Log progress at each step
        results[provider] = summary
    
    print(json.dumps(results, indent=2))
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", nargs="+", default=["Myntra"])
    parser.add_argument("--skip-db", action="store_true")
    args = parser.parse_args()
    run_pipeline(args.providers, args.skip_db)
```

---

### CONFIG (`config/settings.py`)

```python
import os
from dotenv import load_dotenv
load_dotenv()

# API Keys
GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
DATABASE_URL     = os.getenv("DATABASE_URL")

# Models
GROQ_MODEL       = "llama-3.3-70b-versatile"
GROQ_TEMPERATURE = 0
GROQ_MAX_TOKENS  = 2000

# Scraping
COMPETITOR_SITES = {
    "Myntra"  : "https://www.grabon.in/myntra-coupons/",
    "Ajio"    : "https://www.grabon.in/ajio-coupons/",
    "Nykaa"   : "https://www.grabon.in/nykaa-coupons/",
    "Flipkart": "https://www.grabon.in/flipkart-coupons/",
}

# Processing
CHUNK_SIZE       = 3000
CHUNK_OVERLAP    = 200
FUZZY_THRESHOLD  = 85

# Category normalisation map (add more as needed)
CATEGORY_MAP = {
    "sportswear"  : "Sports",
    "sportwear"   : "Sports",
    "apparels"    : "Fashion",
    "apparel"     : "Fashion",
    "women shoes" : "Footwear",
    "men shoes"   : "Footwear",
    "footwears"   : "Footwear",
    "makeup"      : "Beauty",
    "cosmetics"   : "Beauty",
    "skincare"    : "Beauty",
    "mobiles"     : "Electronics",
    "smartphones" : "Electronics",
    "home decor"  : "Home",
    "furniture"   : "Home",
}

# Valid values for validation
VALID_PROMO_TYPES = ["percentage", "flat", "bogo", "bundle", "free_delivery", "other"]
VALID_USER_TYPES  = ["new", "existing", "all"]
VALID_CATEGORIES  = ["Fashion", "Footwear", "Beauty", "Electronics", "Home", "Sports", "Other"]
```

---

### `.env.example`

```
GROQ_API_KEY=your_groq_api_key_here
FIRECRAWL_API_KEY=your_firecrawl_api_key_here
DATABASE_URL=postgresql://postgres:password@localhost:5432/promo_db
```

---

### `requirements.txt`

```
firecrawl-py
groq
rapidfuzz
pydantic
psycopg2-binary
pandas
streamlit
python-dotenv
tenacity
httpx
```

---

## BUILD ORDER & VALIDATION CHECKPOINTS

Build and validate each layer before proceeding:

```
Step 1: Create project structure + config/settings.py + .env.example
        ✓ Validate: python -c "from config.settings import GROQ_MODEL; print(GROQ_MODEL)"

Step 2: Build ingestion/firecrawl_fetcher.py
        ✓ Validate: python -c "from ingestion.firecrawl_fetcher import fetch_promotions;
                    r = fetch_promotions('https://www.grabon.in/myntra-coupons/', 'Myntra');
                    print(r['char_count'])"

Step 3: Build extraction/ (groq_extractor.py + prompt_templates.py)
        ✓ Validate: Run extractor on saved markdown from Step 2
                    Confirm ≥10 offers extracted with valid schema

Step 4: Build processing/post_processor.py
        ✓ Validate: Run processor on Step 3 output
                    Confirm dropped count < 20% of total

Step 5: Build database/ (schema.sql + db_client.py + loader.py)
        ✓ Validate: psql -d promo_db -f database/schema.sql
                    python -c "from database.db_client import DBClient; DBClient().execute('SELECT 1')"

Step 6: Run full pipeline end to end via main.py
        ✓ Validate: python main.py --providers Myntra
                    Check output/ folder, check DB row count

Step 7: Build insights/insights_engine.py
        ✓ Validate: python -c "from insights.insights_engine import run_insight;
                    print(run_insight('avg_discount_by_category', {'days': 7}))"

Step 8: Build recommendations/recommendation_engine.py
        ✓ Validate: python -c "from recommendations.recommendation_engine import get_recommendation;
                    print(get_recommendation('Footwear', 40, 35))"

Step 9: Build chatbot/chat_engine.py
        ✓ Validate: python -c "from chatbot.chat_engine import chat;
                    print(chat('What is Myntra doing in footwear?', []))"

Step 10: Build ui/app.py
         ✓ Validate: streamlit run ui/app.py
                     All 5 screens load without errors
```

---

## CRITICAL RULES — NEVER VIOLATE

1. **Never generate SQL dynamically from user input.** All queries are fixed with `%s` / `%(name)s` parameters only.
2. **Never use LangChain, LangGraph, or any agent framework.**
3. **Never use a vector database.** PostgreSQL is the only database.
4. **All LLM calls go through a single Groq client** initialised in `config/settings.py`.
5. **All prompts live in `extraction/prompt_templates.py`** — never inline prompts in engine files.
6. **Wrap every LLM call in tenacity** with at least 3 retries and exponential backoff.
7. **Validate every LLM JSON output with Pydantic** before it touches the database.
8. **Log every pipeline step** — provider, record count, duration, errors.
9. **The pipeline must be idempotent** — running it twice for the same date must not duplicate DB records.
10. **Streamlit must work with no data** — every screen handles empty DB gracefully with a helpful message.

---

## DEMO SCRIPT (validate this works after Step 10)

```
Minute 1 — Screen 1 (Promotions Table)
  Filter by Myntra + Footwear
  Show structured offers with discount ranges and coupon codes

Minute 2 — Screen 2 (Market Insights)
  Select Footwear category
  Show bar chart + LLM narrative
  "Myntra is leading at X% avg discount..."

Minute 3 — Screen 3 (Recommendation)
  Enter: Category=Footwear, Our discount=40%, Our margin=35%
  Show SITUATION / RECOMMENDATION / REASONING card

Bonus — Screen 5 (AI Assistant)
  Ask: "What should we do about Myntra's footwear campaign?"
  Show full conversational response with tool routing
```

---

*This prompt is self-contained. Build layer by layer. Validate at each checkpoint. The entire POC — ingestion through chatbot — should be runnable in under 6 working days.*
