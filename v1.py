# test_1_no_options.py
# -------------------------------------------------------
# TEST 1 — No scrape options at all
# Raw Firecrawl output, no filtering
# -------------------------------------------------------

import json
import os
from firecrawl import Firecrawl
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.getenv("FIRECRAWL_API_KEY")
TEST_URL = "https://www.coupondunia.in/myntra"

firecrawl = Firecrawl(api_key=API_KEY)

print("TEST 1 — No scrape options (raw output)")
print(f"URL: {TEST_URL}\n")

response = firecrawl.crawl(
    url   = TEST_URL,
    limit = 1           # 1 page only for testing
)

page     = response.data[0]
markdown = page.markdown or ""

print(f"Total characters : {len(markdown):,}")
print(f"Total lines      : {markdown.count(chr(10)):,}")
print("\n--- First 1000 chars ---\n")
print(markdown[:1000])

# Save full output
with open("test_1_output.txt", "w") as f:
    f.write(markdown)

print("\n✅ Full output saved to test_1_output.txt")