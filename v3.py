# # test_3_json_extraction.py
# # -------------------------------------------------------
# # TEST 3 — JSON extraction via formats
# # Firecrawl runs LLM internally, returns structured JSON
# # No separate LLM call needed
# # -------------------------------------------------------

# import json
# import os
# from firecrawl import Firecrawl
# from dotenv import load_dotenv

# load_dotenv()

# API_KEY  = os.getenv("FIRECRAWL_API_KEY")
# TEST_URL = "https://www.coupondunia.in/myntra"

# firecrawl = Firecrawl(api_key=API_KEY)

# print("TEST 3 — JSON extraction via formats")
# print(f"URL: {TEST_URL}\n")

# response = firecrawl.crawl(
#     url   = TEST_URL,
#     limit = 1,
#     scrape_options = {
#         "formats": [
#             {
#                 "type"  : "json",
#                 "prompt": """
#                     Extract all promotional offers from this page.
#                     Each offer should have:
#                     - offer_title : the main headline of the offer
#                     - description : full offer description
#                     - coupon_code : coupon or promo code if present, else null
#                     - discount    : discount value e.g. '40%', '₹500', '50-80%'
#                     - category    : product category e.g. Fashion, Footwear, Beauty
#                     - brand       : specific brand name if mentioned, else null
#                     Only extract actual promotional deals. Ignore navigation and footer.
#                 """,
#                 "schema": {
#                     "type": "object",
#                     "properties": {
#                         "offers": {
#                             "type": "array",
#                             "items": {
#                                 "type": "object",
#                                 "properties": {
#                                     "offer_title" : {"type": "string"},
#                                     "description" : {"type": "string"},
#                                     "coupon_code" : {"type": "string"},
#                                     "discount"    : {"type": "string"},
#                                     "category"    : {"type": "string"},
#                                     "brand"       : {"type": "string"}
#                                 }
#                             }
#                         }
#                     }
#                 }
#             }
#         ]
#     }
# )

# page = response.data[0]

# # JSON is in page.json — already structured, no parsing needed
# extracted = page.json if hasattr(page, "json") and page.json else {}
# offers    = extracted.get("offers", [])

# print(f"Total offers extracted : {len(offers)}")
# print("\n--- First 3 offers ---\n")

# for i, offer in enumerate(offers[:3], 1):
#     print(f"Offer {i}:")
#     for key, value in offer.items():
#         print(f"  {key:15s}: {value}")
#     print()

# # Save full output
# with open("test_3_output.json", "w", encoding="utf-8") as f:
#     json.dump(offers, f, indent=2, ensure_ascii=False)

# print(f"✅ Full JSON saved to test_3_output.json")





# updated_try



# test_4_json_extraction.py
# -------------------------------------------------------
# TEST 4 — JSON extraction via formats
# Fixes: scroll actions for lazy-loaded offers + required schema field
# -------------------------------------------------------

import json
import os
from firecrawl import Firecrawl
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.getenv("FIRECRAWL_API_KEY")
TEST_URL = "https://www.coupondunia.in/myntra"

firecrawl = Firecrawl(api_key=API_KEY)

print("TEST 4 — JSON extraction with scroll actions")
print(f"URL: {TEST_URL}\n")

response = firecrawl.crawl(
    url   = TEST_URL,
    limit = 1,
    scrape_options = {
        "actions": [                                      # ✅ FIX 1: scroll to trigger lazy-loaded offers
            {"type": "scroll", "direction": "down"},
            {"type": "wait",   "milliseconds": 1500},
            {"type": "scroll", "direction": "down"},
            {"type": "wait",   "milliseconds": 1500},
            {"type": "scroll", "direction": "down"},
            {"type": "wait",   "milliseconds": 1500},
            {"type": "scroll", "direction": "down"},
            {"type": "wait",   "milliseconds": 1000},
        ],
        "formats": [
            {
                "type"  : "json",
                "prompt": """
                    Extract EVERY promotional offer, coupon, and deal on this page.
                    There may be 20-30+ offers — extract ALL of them without stopping early.
                    Each offer should have:
                    - offer_title : the main headline of the offer
                    - description : full offer description
                    - coupon_code : coupon or promo code if present, else null
                    - discount    : discount value e.g. '40%', '₹500', '50-80%'
                    - category    : product category e.g. Fashion, Footwear, Beauty
                    - brand       : specific brand name if mentioned, else null
                    Only extract actual promotional deals. Ignore navigation, login popups, and footer.
                """,
                "schema": {
                    "type": "object",
                    "properties": {
                        "offers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "offer_title" : {"type": "string"},
                                    "description" : {"type": "string"},
                                    "coupon_code" : {"type": ["string", "null"]},  # ✅ allows null
                                    "discount"    : {"type": "string"},
                                    "category"    : {"type": "string"},
                                    "brand"       : {"type": ["string", "null"]}   # ✅ allows null
                                }
                            }
                        }
                    },
                    "required": ["offers"]                # ✅ FIX 2: forces complete extraction
                }
            }
        ]
    }
)

page      = response.data[0]
extracted = page.json if hasattr(page, "json") and page.json else {}
offers    = extracted.get("offers", [])


# Save full output
with open("test_5_output.json", "w", encoding="utf-8") as f:
    json.dump(offers, f, indent=2, ensure_ascii=False)

print(f"✅ Full JSON saved to test_5_output.json")