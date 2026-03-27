# test_2_with_options.py
# -------------------------------------------------------
# TEST 2 — With scrape options
# onlyMainContent + excludeTags filtering
# -------------------------------------------------------

import json
import os
from firecrawl import Firecrawl
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.getenv("FIRECRAWL_API_KEY")
TEST_URL = "https://www.grabon.in/myntra-coupons/"

firecrawl = Firecrawl(api_key=API_KEY)

print("TEST 2 — With scrape options (onlyMainContent + excludeTags)")
print(f"URL: {TEST_URL}\n")

response = firecrawl.crawl(
    url   = TEST_URL,
    limit = 1,
    scrape_options = {
        "formats"        : ["markdown"],
        "onlyMainContent": True,
        "excludeTags"    : [
            "nav", "footer", "header",
            "script", "style", "noscript",
            ".sidebar", ".popup", ".modal",
            ".cookie-banner", ".newsletter",
            ".breadcrumb", ".pagination-nav",
            ".social-share", ".related-links",
            "#ad", "#ads", ".advertisement"
        ]
    }
)

page     = response.data[0]
markdown = page.markdown or ""

print(f"Total characters : {len(markdown):,}")
print(f"Total lines      : {markdown.count(chr(10)):,}")
print("\n--- First 1000 chars ---\n")
print(markdown[:1000])

# Save full output
with open("test_2_output.txt", "w") as f:
    f.write(markdown)

print("\n✅ Full output saved to test_2_output.txt")