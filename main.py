import json
import os
from config.settings import FIRECRAWL_API_KEY, SITES, OUTPUT_DIR, OUTPUT_FILE
from fetcher.firecrawl_fetcher import fetch_all_sites


def run():

    # -------------------------------------------------------
    # Validate API key
    # -------------------------------------------------------
    if not FIRECRAWL_API_KEY or FIRECRAWL_API_KEY == "your_firecrawl_api_key_here":
        print("\n❌ ERROR: FIRECRAWL_API_KEY not set")
        print("   1. Open .env file")
        print("   2. Set FIRECRAWL_API_KEY=your_real_key")
        print("   3. Get a key at: https://www.firecrawl.dev\n")
        return

    # -------------------------------------------------------
    # Step 1: Fetch all pages from all sites
    # -------------------------------------------------------
    pages = fetch_all_sites(SITES, FIRECRAWL_API_KEY)

    if not pages:
        print("❌ No pages fetched. Check your API key and URLs.")
        return

    # -------------------------------------------------------
    # Step 2: Save raw markdown output to JSON
    #         (so you can inspect before passing to LLM)
    # -------------------------------------------------------
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pages, f, indent=2, ensure_ascii=False)

    print(f"✅ Raw pages saved to: {output_path}")
    print(f"   Open this file to verify markdown before Task 2 (LLM extraction)\n")


if __name__ == "__main__":
    run()