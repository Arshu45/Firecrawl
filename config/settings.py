import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ───────────────────────────────────────────
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
DATABASE_URL      = os.getenv("DATABASE_URL", "")

# ── Models ─────────────────────────────────────────────
GROQ_MODEL       = "llama-3.3-70b-versatile"
GROQ_TEMPERATURE = 0
GROQ_MAX_TOKENS  = 2000

# ── Sites to scrape ────────────────────────────────────
# Dict format: { "ProviderName": "url" }
COMPETITOR_SITES = {
    "Myntra"  : "https://www.grabon.in/myntra-coupons/",
    # "Ajio"    : "https://www.grabon.in/ajio-coupons/",
    "Nykaa"   : "https://www.grabon.in/nykaa-coupons/"
    # "Flipkart": "https://www.grabon.in/flipkart-coupons/",
}

# ── Processing ─────────────────────────────────────────
CHUNK_SIZE      = 5000   # characters per chunk sent to Groq
CHUNK_OVERLAP   = 200     # characters of overlap between chunks
FUZZY_THRESHOLD = 85      # minimum rapidfuzz ratio to consider titles duplicate

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

# ── Output directory ───────────────────────────────────
OUTPUT_DIR = "output"