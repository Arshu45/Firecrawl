import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ───────────────────────────────────────────
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
DATABASE_URL      = os.getenv("DATABASE_URL", "")

# ── App settings ───────────────────────────────────────
CLIENT_BRAND = os.getenv("CLIENT_BRAND", "Westside")
DEFAULT_TOP_COMPETITORS_LIMIT = int(os.getenv("DEFAULT_TOP_COMPETITORS_LIMIT", "5"))
DEFAULT_ACTIVE_OFFERS_LIMIT   = int(os.getenv("DEFAULT_ACTIVE_OFFERS_LIMIT", "5"))
CHAT_HISTORY_WINDOW = int(os.getenv("CHAT_HISTORY_WINDOW", "6"))
TOOL_SUMMARY_TOP_OFFERS = int(os.getenv("TOOL_SUMMARY_TOP_OFFERS", "3"))
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/api/chat")
DB_MIN_CONN = int(os.getenv("DB_MIN_CONN", "1"))
DB_MAX_CONN = int(os.getenv("DB_MAX_CONN", "10"))

# ── MySQL Integration ──────────────────────────────────
MYSQL_HOST = os.getenv("MYSQL_HOST", "172.27.133.173")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "readonly_user")
MYSQL_PASS = os.getenv("MYSQL_PASS", "cybage@123")
MYSQL_DB   = os.getenv("MYSQL_DB", "fashion_retail")

# ── Models ─────────────────────────────────────────────
GROQ_MODEL       = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0"))
GROQ_MAX_TOKENS  = int(os.getenv("GROQ_MAX_TOKENS", "2000"))

# ── Sites to scrape ────────────────────────────────────
# Dict format: { "ProviderName": "url" }
COMPETITOR_SITES = {
    "Myntra"  : "https://www.grabon.in/myntra-coupons/",
    # "Ajio"    : "https://www.grabon.in/ajio-coupons/",
    "Nykaa"   : "https://www.grabon.in/nykaa-coupons/"
    # "Flipkart": "https://www.grabon.in/flipkart-coupons/",
}

# ── Processing ─────────────────────────────────────────
CHUNK_SIZE      = int(os.getenv("CHUNK_SIZE", "5000"))   # characters per chunk sent to Groq
CHUNK_OVERLAP   = int(os.getenv("CHUNK_OVERLAP", "200")) # characters of overlap between chunks
FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", "85")) # minimum rapidfuzz ratio to consider titles duplicate

# ── Category normalisation map ─────────────────────────
# Keys are case-insensitive; values are canonical category names
CATEGORY_MAP = {
    "sportswear"  : "Sports",
    "sportwear"   : "Sports",
    "apparels"    : "Fashion",
    "apparel"     : "Fashion",
    "clothing"    : "Fashion",
    "women shoes" : "Footwear",
    "men shoes"   : "Footwear",
    "footwears"   : "Footwear",
    "shoes"       : "Footwear",
    "makeup"      : "Beauty",
    "cosmetics"   : "Beauty",
    "skincare"    : "Beauty",
    "beauty care" : "Beauty",
    "mobiles"     : "Electronics",
    "smartphones" : "Electronics",
    "gadgets"     : "Electronics",
    "home decor"  : "Home",
    "furniture"   : "Home",
    "jewellery"   : "Jewellery",
    "jewelry"     : "Jewellery",
}

# ── Valid enum values (used by Pydantic + post-processor) ─
VALID_PROMO_TYPES = ["percentage", "flat", "bogo", "bundle", "free_delivery", "other"]
VALID_USER_TYPES  = ["new", "existing", "all"]
VALID_CATEGORIES  = ["Fashion", "Footwear", "Beauty", "Electronics", "Home", "Sports", "Jewellery", "Other"]

# ── Agent Understanding Rules ──────────────────────────
KNOWN_CATEGORIES = {
    "fashion", "footwear", "beauty", "electronics",
    "home", "sports", "jewellery", "jewelry",
}
ANALYSIS_HINTS = {
    "trend", "trends", "discount", "discounts", "offer", "offers",
    "competitor", "competitors", "category", "categories", "pricing",
    "price", "market", "strategy", "recommend", "recommendation",
    "promotions", "promotion", "analyze", "analysis", "compare",
}

# ── Output directory ───────────────────────────────────
OUTPUT_DIR = "output"
