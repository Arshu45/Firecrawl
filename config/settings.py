import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

# ✅ Batch-based config
SITES = [
    {
        "provider": "Myntra",
        "urls": [
            "https://www.coupondunia.in/myntra?subcategories=&banks=&sortBy=popularity&noOfPages=3&tab=all&userType=all",
            "https://www.coupondunia.in/myntra?subcategories=&banks=&sortBy=popularity&noOfPages=2&tab=all&userType=all",
            "https://www.coupondunia.in/myntra?subcategories=&banks=&sortBy=popularity&noOfPages=1&tab=all&userType=all"
        ]
    },

    # Example future batch
    # {
    #     "provider": "Ajio",
    #     "urls": [
    #         "https://...",
    #         "https://..."
    #     ]
    # }
]

OUTPUT_DIR  = "output"
OUTPUT_FILE = f"promotions_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"