from datetime import date
from firecrawl import Firecrawl


def fetch_page_markdown(url: str, provider: str, api_key: str) -> dict | None:
    """
    Scrapes a single URL using Firecrawl and returns raw Markdown.

    Uses:
    - formats=["markdown"]  — plain text output, no LLM involved
    - onlyMainContent=True  — strips nav, footer, sidebar automatically
    - excludeTags           — removes remaining junk HTML elements
    - scroll actions x12    — triggers lazy-loaded offer cards

    Returns:
        { "url", "provider", "scraped_date", "markdown" }
        or None if scrape failed / too short
    """

    print(f"\n  [{provider}] Scraping: {url}")

    firecrawl = Firecrawl(api_key=api_key)

    # Build scroll actions — 12 scrolls with 2s wait each
    # This ensures lazy-loaded content (e.g. GrabOn's 52 offers) fully loads
    actions = []
    for _ in range(12):
        actions.append({"type": "scroll", "direction": "down"})
        actions.append({"type": "wait", "milliseconds": 2000})

    try:
        response = firecrawl.scrape(
            url,
            formats          = ["markdown"],
            actions          = actions,
            only_main_content = True,
            exclude_tags     = [
                "nav", "footer", "header",
                "script", "style", "noscript",
                ".sidebar", ".popup", ".modal",
                ".cookie-banner", ".newsletter",
                ".breadcrumb", ".pagination-nav",
                ".social-share", ".related-links",
                "#ad", "#ads", ".advertisement"
            ],
            timeout          = 120000,   # 2 min — give scroll actions time to complete
        )

        markdown = response.markdown if hasattr(response, "markdown") else ""

        if not markdown or len(markdown.strip()) < 200:
            print(f"  [{provider}] ⚠️  Skipped — content too short ({len(markdown)} chars)")
            return None

        print(f"  [{provider}] ✅ {len(markdown):,} chars scraped")

        return {
            "url"          : url,
            "provider"     : provider,
            "scraped_date" : date.today().isoformat(),
            "markdown"     : markdown
        }

    except Exception as e:
        print(f"  [{provider}] ❌ Scrape failed: {str(e)}")
        return None


def fetch_all_sites(sites: list, api_key: str) -> list:
    """
    Iterates through all configured sites and fetches each URL.

    Config format expected:
        [
            {
                "provider": "Myntra",
                "urls": ["https://...", "https://..."]
            }
        ]

    Returns:
        Flat list of scraped pages:
        [
            { "url", "provider", "scraped_date", "markdown" },
            ...
        ]
    """

    all_pages  = []
    total_urls = sum(len(site.get("urls", [])) for site in sites)

    print(f"\n{'='*55}")
    print(f"  FETCH STARTING")
    print(f"  Sites    : {len(sites)}")
    print(f"  Total URLs: {total_urls}")
    print(f"{'='*55}")

    for site in sites:
        provider = site["provider"]
        urls     = site.get("urls", [])

        print(f"\n  [{provider}] — {len(urls)} URL(s)")

        for url in urls:
            page = fetch_page_markdown(url, provider, api_key)
            if page:
                all_pages.append(page)

    print(f"\n{'='*55}")
    print(f"  FETCH COMPLETE")
    print(f"  Pages scraped : {len(all_pages)} / {total_urls}")
    print(f"{'='*55}\n")

    return all_pages