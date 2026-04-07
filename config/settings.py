import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ───────────────────────────────────────────
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY",      "")
DATABASE_URL      = os.getenv("DATABASE_URL",       "")

# ── Models ─────────────────────────────────────────────
GROQ_MODEL       = "llama-3.3-70b-versatile"
GROQ_TEMPERATURE = 0
GROQ_MAX_TOKENS  = 2000

# ── Scraping ───────────────────────────────────────────
COMPETITOR_SITES = {
    "Myntra"  : "https://www.grabon.in/myntra-coupons/",
    # "Urbanic" : "https://www.grabon.in/urbanic-coupons/",
    # "Nykaa"   : "https://www.grabon.in/levis-coupons/",
    'Meesho' : "https://www.grabon.in/meesho-coupons/",
    "Tata Cliq" : "https://www.grabon.in/tatacliq-coupons/" 
}

# ── Processing ─────────────────────────────────────────
CHUNK_SIZE      = 10000   # characters per LLM chunk
CHUNK_OVERLAP   = 200    # overlap to avoid cutting offers mid-way
FUZZY_THRESHOLD = 85     # rapidfuzz ratio threshold for dedup

# ── Category normalisation map ─────────────────────────
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

# ── Valid field values ──────────────────────────────────
VALID_PROMO_TYPES = ["percentage", "flat", "bogo", "bundle", "free_delivery", "other"]
VALID_USER_TYPES  = ["new", "existing", "all"]
VALID_CATEGORIES  = ["Fashion", "Footwear", "Beauty", "Electronics", "Home", "Sports", "Other"]

# ── Output ─────────────────────────────────────────────
OUTPUT_DIR = "output"