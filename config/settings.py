import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ── API Keys ───────────────────────────────────────────
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY",      "")

# ── Model ──────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Sites to scrape ─────────────────────────────────────
SITES = [
    {
        "provider": "Myntra",
        "urls": [
            "https://www.grabon.in/myntra-coupons/"
        ]
    },
    {
        "provider": "Nykaa",
        "urls": [
            "https://www.grabon.in/nykaa-coupons/"
        ]
    }

    # Add more providers here:
    # {
    #     "provider": "Ajio",
    #     "urls": [
    #         "https://www.grabon.in/ajio-coupons/",
    #     ]
    # },
]

# ── Output ─────────────────────────────────────────────
OUTPUT_DIR = "output"