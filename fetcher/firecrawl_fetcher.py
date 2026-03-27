# from firecrawl import Firecrawl
# from urllib.parse import urlparse


# Crawling way + Markdown Output

# def get_include_path(url: str) -> list:
#     """
#     Extracts the path from the URL so crawl stays
#     on only that retailer's pages.

#     Example:
#         https://www.coupondunia.in/ajio     →  ["/ajio"]
#         https://www.grabon.in/ajio-coupons/ →  ["/ajio-coupons"]
#     """
#     path = urlparse(url).path.rstrip("/")
#     return [path] if path else []


# def fetch_all_pages(url: str, provider: str, api_key: str, limit: int = 5) -> list:

#     print(f"\n{'='*55}")
#     print(f"  [{provider}] Starting crawl")
#     print(f"  URL   : {url}")
#     print(f"  Limit : {limit} pages")
#     print(f"{'='*55}")

#     firecrawl     = Firecrawl(api_key=api_key)
#     include_paths = get_include_path(url)

#     print(f"  Restricting crawl to paths: {include_paths}")

#     try:
#         response = firecrawl.crawl(
#             url                     = url,
#             limit                   = limit,
#             include_paths           = include_paths,
#             ignore_query_parameters = False,
#             scrape_options          = {
#                 "formats": ["markdown"],

#                 # Step 1 — Firecrawl built-in content filter
#                 # Removes boilerplate automatically on every site             
#                 "onlyMainContent": True,

#                 # Step 2 — Exclude remaining junk by HTML tag / class
#                 # Standard HTML tags — works on every site, no maintenance needed
#                 "excludeTags": [
#                     "nav", "footer", "header",
#                     "script", "style", "noscript",
#                     ".sidebar", ".popup", ".modal",
#                     ".cookie-banner", ".newsletter",
#                     ".breadcrumb", ".pagination-nav",
#                     ".social-share", ".related-links",
#                     "#ad", "#ads", ".advertisement"
#                 ]
#             }
#         )

#         if not response or not response.data:
#             print(f"  [{provider}] ⚠️  No data returned")
#             return []

#         results = []

#         for i, page in enumerate(response.data, 1):

#             markdown = page.markdown if hasattr(page, "markdown") else ""

#             # DocumentMetadata is a Pydantic object — use getattr, not .get()
#             source_url = url
#             if hasattr(page, "metadata") and page.metadata:
#                 source_url = (
#                     getattr(page.metadata, "source_url", None)
#                     or getattr(page.metadata, "sourceURL", None)
#                     or url
#                 )

#             if not markdown or len(markdown.strip()) < 100:
#                 print(f"  [{provider}] ⚠️  Page {i} skipped — too short or empty")
#                 continue

#             print(f"  [{provider}] ✅ Page {i} — {len(markdown):,} chars — {source_url}")

#             results.append({
#                 "url"      : source_url,
#                 "provider" : provider,
#                 "markdown" : markdown
#             })

#         print(f"\n  [{provider}] Done — {len(results)} pages fetched")
#         return results

#     except Exception as e:
#         print(f"  [{provider}] ❌ Crawl failed: {str(e)}")
#         return []


# def fetch_all_sites(sites: list, api_key: str) -> list:
#     """
#     Loops through all configured sites and fetches each one.

#     Returns:
#         Flat list of all pages fetched across all sites
#         [
#             { "url": ..., "provider": ..., "markdown": ... },
#             ...
#         ]
#     """

#     all_pages = []

#     for site in sites:
#         pages = fetch_all_pages(
#             url      = site["url"],
#             provider = site["provider"],
#             api_key  = api_key,
#             limit    = site.get("limit", 5)
#         )
#         all_pages.extend(pages)

#     print(f"\n{'='*55}")
#     print(f"  FETCH COMPLETE")
#     print(f"  Total pages fetched : {len(all_pages)}")
#     print(f"  Across {len(sites)} sites")
#     print(f"{'='*55}\n")

#     return all_pages





# Crawling way + JSON Output 

# from firecrawl import Firecrawl
# from urllib.parse import urlparse


# def get_include_path(url: str) -> list:
#     path = urlparse(url).path.rstrip("/")
#     return [path] if path else []


# def fetch_all_pages(url: str, provider: str, api_key: str, limit: int = 5) -> list:

#     print(f"\n{'='*55}")
#     print(f"  [{provider}] Starting crawl")
#     print(f"  URL   : {url}")
#     print(f"  Limit : {limit} pages")
#     print(f"{'='*55}")

#     firecrawl     = Firecrawl(api_key=api_key)
#     # include_paths = get_include_path(url)
#     include_paths = None

#     print(f"  Restricting crawl to paths: {include_paths}")

#     try:
#         response = firecrawl.crawl(
#             url                     = url,
#             limit                   = limit,
#             include_paths           = include_paths,
#             ignore_query_parameters = False,
#             scrape_options = {
#                 "actions": [
#                     {"type": "scroll", "direction": "down"},
#                     {"type": "wait",   "milliseconds": 1500},
#                     {"type": "scroll", "direction": "down"},
#                     {"type": "wait",   "milliseconds": 1500},
#                     {"type": "scroll", "direction": "down"},
#                     {"type": "wait",   "milliseconds": 1500},
#                     {"type": "scroll", "direction": "down"},
#                     {"type": "wait",   "milliseconds": 1000},
#                 ],
#                 "formats": [
#                     {
#                         "type": "json",
#                         "prompt": """
#                     Extract EVERY promotional offer, coupon, and deal on this page.
#                     There may be 20-30+ offers — extract ALL of them without stopping early.
#                     Each offer should have:
#                     - offer_title : the main headline of the offer
#                     - description : full offer description
#                     - coupon_code : coupon or promo code if present, else null
#                     - discount    : discount value e.g. '40%', '₹500', '50-80%'
#                     - category    : product category e.g. Fashion, Footwear, Beauty
#                     - brand       : specific brand name if mentioned, else null
#                     Only extract actual promotional deals. Ignore navigation, login popups, and footer.
#                 """,
#                         "schema": {
#                             "type": "object",
#                             "properties": {
#                                 "offers": {
#                                     "type": "array",
#                                     "items": {
#                                         "type": "object",
#                                         "properties": {
#                                             "offer_title" : {"type": "string"},
#                                             "description" : {"type": "string"},
#                                             "coupon_code" : {"type": ["string", "null"]},
#                                             "discount"    : {"type": "string"},
#                                             "category"    : {"type": "string"},
#                                             "brand"       : {"type": ["string", "null"]}
#                                         }
#                                     }
#                                 }
#                             },
#                             "required": ["offers"]
#                         }
#                     }
#                 ]
#             }
#         )

#         if not response or not response.data:
#             print(f"  [{provider}] ⚠️  No data returned")
#             return []

#         results = []

#         for i, page in enumerate(response.data, 1):

#             # ✅ FIX: read JSON instead of markdown
#             data = page.json if hasattr(page, "json") else None

#             source_url = url
#             if hasattr(page, "metadata") and page.metadata:
#                 source_url = (
#                     getattr(page.metadata, "source_url", None)
#                     or getattr(page.metadata, "sourceURL", None)
#                     or url
#                 )

#             # ✅ FIX: validate JSON instead of markdown length
#             if not data or "offers" not in data or len(data["offers"]) == 0:
#                 print(f"  [{provider}] ⚠️  Page {i} skipped — no offers found")
#                 continue

#             print(f"  [{provider}] ✅ Page {i} — {len(data['offers'])} offers — {source_url}")

#             results.append({
#                 "url"      : source_url,
#                 "provider" : provider,
#                 "offers"   : data["offers"]
#             })

#         print(f"\n  [{provider}] Done — {len(results)} pages fetched")
#         return results

#     except Exception as e:
#         print(f"  [{provider}] ❌ Crawl failed: {str(e)}")
#         return []


# def fetch_all_sites(sites: list, api_key: str) -> list:

#     all_pages = []

#     for site in sites:
#         pages = fetch_all_pages(
#             url      = site["url"],
#             provider = site["provider"],
#             api_key  = api_key,
#             limit    = site.get("limit", 5)
#         )
#         all_pages.extend(pages)

#     print(f"\n{'='*55}")
#     print(f"  FETCH COMPLETE")
#     print(f"  Total pages fetched : {len(all_pages)}")
#     print(f"  Across {len(sites)} sites")
#     print(f"{'='*55}\n")

#     return all_pages






# Scraping way + JSON Structured Output

from firecrawl import Firecrawl


def fetch_all_pages(urls: list, provider: str, api_key: str) -> list:

    print(f"\n{'='*55}")
    print(f"  [{provider}] Starting scrape")
    print(f"  Total URLs : {len(urls)}")
    print(f"{'='*55}")

    firecrawl = Firecrawl(api_key=api_key)

    results = []

    try:
        for i, url in enumerate(urls, 1):

            print(f"\n  [{provider}] Scraping URL {i}: {url}")

            page = firecrawl.scrape(
                url,

                formats=[
                    {
                        "type": "json",
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
                                            "offer_title": {"type": "string"},
                                            "description": {"type": "string"},
                                            "coupon_code": {"type": ["string", "null"]},
                                            "discount": {"type": "string"},
                                            "category": {"type": "string"},
                                            "brand": {"type": ["string", "null"]}
                                        }
                                    }
                                }
                            },
                            "required": ["offers"]
                        }
                    }
                ],

                actions=[
                    {"type": "scroll", "direction": "down"},
                    {"type": "wait", "milliseconds": 1500},
                    {"type": "scroll", "direction": "down"},
                    {"type": "wait", "milliseconds": 1500},
                    {"type": "scroll", "direction": "down"},
                    {"type": "wait", "milliseconds": 1500},
                ]
            )

            # ✅ FIX: no .data
            data = page.json if hasattr(page, "json") else None

            if not data or "offers" not in data or len(data["offers"]) == 0:
                print(f"  [{provider}] ⚠️ No offers found")
                continue

            print(f"  [{provider}] ✅ {len(data['offers'])} offers found")

            results.append({
                "url": url,
                "provider": provider,
                "offers": data["offers"]
            })

        print(f"\n  [{provider}] Done — {len(results)} pages fetched")
        return results

    except Exception as e:
        print(f"  [{provider}] ❌ Scrape failed: {str(e)}")
        return []


def fetch_all_sites(sites: list, api_key: str) -> list:

    all_pages = []

    for site in sites:
        provider = site["provider"]
        urls     = site["urls"]

        pages = fetch_all_pages(
            urls=urls,
            provider=provider,
            api_key=api_key
        )

        all_pages.extend(pages)

    print(f"\n{'='*55}")
    print(f"  FETCH COMPLETE")
    print(f"  Total pages fetched : {len(all_pages)}")
    print(f"  Across {len(sites)} providers")
    print(f"{'='*55}\n")

    return all_pages