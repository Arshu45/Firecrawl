import json
import time
from datetime import date

from groq import Groq


# -------------------------------------------------------
# Config
# -------------------------------------------------------

# Groq free tier: 12,000 TPM per request
# ~1 char ≈ 0.25 tokens
# Safe chunk size: 10,000 chars ≈ 2,500 tokens input
# + ~450 tokens overhead (system + prompt template)
# + ~1,200 tokens output (~8-10 offers per chunk)
# = ~4,150 tokens per call — well within 12k limit
# (20k chunks caused ~3,250 output tokens which truncated mid-JSON)
CHUNK_SIZE_CHARS = 10_000   # characters per chunk sent to Groq


# -------------------------------------------------------
# Prompts
# -------------------------------------------------------

SYSTEM_PROMPT = """You are a precise data extraction assistant.
Your job is to extract promotional offers from coupon/deal website content.
You MUST return a valid JSON object with a single key "offers" containing an array of offer objects.
Example: {"offers": [{...}, {...}]}
If you find no offers, return: {"offers": []}
"""

USER_PROMPT_TEMPLATE = """Extract EVERY promotional offer, coupon, and deal from the markdown below.
This is a chunk of a larger page — extract ALL offers you find in this section.

Return a JSON object: {{"offers": [list of offer objects]}}

For each offer extract these exact fields:
- offer_title  : main headline of the offer (string)
- description  : full offer description (string)
- brand        : specific brand name if mentioned, else null
- category     : one of: Fashion / Footwear / Beauty / Electronics / Food / Travel / Home / Sports / Jewellery / Other
- promo_type   : one of: percentage | percentage_range | flat_amount | bogo | price_point | bundle | free_delivery
- discount_min : lowest discount % as integer (e.g. 50 from "50-80% Off"), null if not applicable
- discount_max : highest discount % as integer (e.g. 80 from "50-80% Off"), null if not applicable
- flat_value   : flat rupee discount as integer (e.g. 300 from "Rs 300 Off"), null if not present
- min_purchase : minimum purchase amount as integer (e.g. 1999 from "orders above Rs 1999"), null if not mentioned
- coupon_code  : coupon or promo code string if present, null if none
- user_type    : "new_user" or "existing_user" or "all" (default "all" if not specified)

Rules:
- Only extract actual promotional deals.
- Ignore navigation, login popups, cashback rate tables, testimonials, and footer.

--- MARKDOWN START ---
{markdown}
--- MARKDOWN END ---
"""


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------


def _chunk_markdown(markdown: str, chunk_size: int = CHUNK_SIZE_CHARS) -> list[str]:
    """
    Splits markdown into chunks of at most `chunk_size` characters.
    Splits on blank lines to avoid cutting in the middle of an offer block.
    """
    paragraphs = markdown.split("\n\n")
    chunks     = []
    current    = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for the \n\n separator
        if current_len + para_len > chunk_size and current:
            chunks.append("\n\n".join(current))
            current     = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _call_groq(chunk: str, client: Groq, model: str, provider: str, chunk_num: int) -> list:
    """
    Sends one markdown chunk to Groq and returns a list of offer dicts.
    Retries once on JSON parse error.
    """
    user_prompt = USER_PROMPT_TEMPLATE.format(markdown=chunk)

    for attempt in range(1, 3):
        try:
            response = client.chat.completions.create(
                model           = model,
                temperature     = 0,
                max_tokens      = 4096,   # raised: chunks 1&2 were hitting 2048 ceiling, dropping offers
                response_format = {"type": "json_object"},  # ← forces valid JSON every time
                messages        = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ]
            )

            raw_content = response.choices[0].message.content or "{}"
            parsed      = json.loads(raw_content)   # always valid JSON — guaranteed by Groq
            offers      = parsed.get("offers", [])

            if not isinstance(offers, list):
                raise ValueError(f"Expected offers list, got: {type(offers)}")

            usage = response.usage
            print(f"  [{provider}] Chunk {chunk_num} ✅  {len(offers)} offers "
                  f"| tokens in:{usage.prompt_tokens} out:{usage.completion_tokens}")
            return offers

        except Exception as e:
            # Rate limit — back off and retry
            if "rate_limit" in str(e).lower() or "429" in str(e):
                wait = 62
                print(f"  [{provider}] Chunk {chunk_num} ⏳ Rate limit — waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"  [{provider}] Chunk {chunk_num} ❌ Error (attempt {attempt}/2): {str(e)}")
            if attempt == 2:
                return []
            time.sleep(15)

    return []


# -------------------------------------------------------
# Public API
# -------------------------------------------------------

def extract_offers_from_page(page: dict, client: Groq, model: str) -> dict | None:
    """
    Chunks the page markdown and calls Groq on each chunk.
    Merges all offers into a single result.

    Args:
        page   : { url, provider, scraped_date, markdown }
        client : Groq client instance
        model  : model name string

    Returns:
        { source_url, provider, scraped_date, offers: [...] }
        or None if nothing extracted
    """
    provider = page["provider"]
    url      = page["url"]
    markdown = page["markdown"]

    chunks = _chunk_markdown(markdown)

    print(f"\n  [{provider}] Extracting from: {url}")
    print(f"  [{provider}] Markdown: {len(markdown):,} chars → {len(chunks)} chunk(s) of ~{CHUNK_SIZE_CHARS:,} chars")

    all_offers = []

    for i, chunk in enumerate(chunks, 1):
        offers = _call_groq(chunk, client, model, provider, chunk_num=i)
        all_offers.extend(offers)

        # Pause between chunks to respect TPM limits (12k tokens/min)
        if i < len(chunks):
            time.sleep(5)

    if not all_offers:
        print(f"  [{provider}] ❌ No offers found across all chunks.")
        return None

    # Deduplicate by coupon_code + offer_title
    seen      = set()
    deduped   = []
    for offer in all_offers:
        key = (offer.get("coupon_code"), offer.get("offer_title", "").lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(offer)

    removed = len(all_offers) - len(deduped)
    print(f"\n  [{provider}] 🎉 Total: {len(deduped)} unique offers"
          + (f" ({removed} duplicates removed)" if removed else ""))

    return {
        "source_url"   : url,
        "provider"     : provider,
        "scraped_date" : page.get("scraped_date", date.today().isoformat()),
        "offers"       : deduped
    }


def extract_all_pages(pages: list, groq_api_key: str, model: str) -> list:
    """
    Runs Groq extraction on every scraped page.

    Args:
        pages        : list of { url, provider, scraped_date, markdown }
        groq_api_key : Groq API key
        model        : Groq model name

    Returns:
        list of { source_url, provider, scraped_date, offers: [...] }
    """
    client       = Groq(api_key=groq_api_key)
    results      = []
    total_offers = 0

    print(f"\n{'='*55}")
    print(f"  EXTRACTION STARTING")
    print(f"  Pages to process : {len(pages)}")
    print(f"  Model            : {model}")
    print(f"  Chunk size       : {CHUNK_SIZE_CHARS:,} chars")
    print(f"{'='*55}")

    for i, page in enumerate(pages):
        result = extract_offers_from_page(page, client, model)
        if result:
            results.append(result)
            total_offers += len(result["offers"])

        # Cooldown between pages to avoid TPM spike from back-to-back chunks
        if i < len(pages) - 1:
            print(f"\n  ⏸  Inter-page cooldown (10s)...")
            time.sleep(10)

    print(f"\n{'='*55}")
    print(f"  EXTRACTION COMPLETE")
    print(f"  Pages processed  : {len(results)} / {len(pages)}")
    print(f"  Total offers     : {total_offers}")
    print(f"{'='*55}\n")

    return results
