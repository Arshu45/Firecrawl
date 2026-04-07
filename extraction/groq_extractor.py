"""
Layer 1 — AI Extraction
Converts raw Markdown → validated, structured Offer objects via Groq LLM.

Public API:
    extract_from_page(page: dict) -> dict | None
    extract_all(pages: list)      -> list[dict]
"""

import json
import os
import time
import logging
from datetime import date
from typing import Optional

from groq import Groq
from pydantic import BaseModel, field_validator, model_validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import (
    GROQ_API_KEY, GROQ_MODEL, GROQ_MAX_TOKENS, GROQ_TEMPERATURE,
    CHUNK_SIZE, CHUNK_OVERLAP, OUTPUT_DIR, VALID_PROMO_TYPES, VALID_USER_TYPES,
)
from extraction.prompt_templates import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT

logger = logging.getLogger(__name__)


# ── Pydantic Offer model ───────────────────────────────────────────────────────

class Offer(BaseModel):
    offer_title  : str
    description  : Optional[str]  = None
    brand        : Optional[str]  = None
    category     : Optional[str]  = None
    promo_type   : str            = "other"
    discount_min : Optional[float] = None
    discount_max : Optional[float] = None
    flat_value   : Optional[float] = None
    min_purchase : Optional[float] = None
    coupon_code  : Optional[str]  = None
    user_type    : str             = "all"
    valid_until  : Optional[str]  = None

    @field_validator("promo_type")
    @classmethod
    def normalise_promo_type(cls, v):
        v = v.lower().strip() if v else "other"
        # Map legacy values from old extractor
        _map = {
            "percentage_range": "percentage",
            "flat_amount"     : "flat",
            "price_point"     : "flat",
        }
        v = _map.get(v, v)
        return v if v in VALID_PROMO_TYPES else "other"

    @field_validator("user_type")
    @classmethod
    def normalise_user_type(cls, v):
        v = (v or "all").lower().strip()
        _map = {
            "new_user"      : "new",
            "existing_user" : "existing",
        }
        v = _map.get(v, v)
        return v if v in VALID_USER_TYPES else "all"

    @field_validator("offer_title")
    @classmethod
    def title_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("offer_title cannot be empty")
        return v.strip()


# ── Chunking ───────────────────────────────────────────────────────────────────

def _chunk_markdown(markdown: str) -> list[str]:
    """
    Splits markdown into chunks of ~CHUNK_SIZE chars with CHUNK_OVERLAP overlap.
    Splits on blank lines to avoid cutting mid-offer.
    """
    paragraphs  = markdown.split("\n\n")
    chunks      = []
    current     = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2   # +2 for \n\n

        if current_len + para_len > CHUNK_SIZE and current:
            chunk_text = "\n\n".join(current)
            chunks.append(chunk_text)

            # Roll back by CHUNK_OVERLAP chars to create overlap
            overlap_text = chunk_text[-CHUNK_OVERLAP:]
            current      = [overlap_text, para]
            current_len  = len(overlap_text) + para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


# ── Groq call (with tenacity) ──────────────────────────────────────────────────

def _is_rate_limit(exc: Exception) -> bool:
    return "rate_limit" in str(exc).lower() or "429" in str(exc)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=15, max=65),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _call_groq(chunk: str, client: Groq, provider: str, chunk_num: int) -> list[Offer]:
    """
    Sends one markdown chunk to Groq, validates each offer with Pydantic.
    Returns list of valid Offer objects. Drops failed ones with a warning.
    """
    prompt = EXTRACTION_USER_PROMPT.format(markdown_chunk=chunk)

    response = client.chat.completions.create(
        model           = GROQ_MODEL,
        temperature     = GROQ_TEMPERATURE,
        max_tokens      = GROQ_MAX_TOKENS,
        response_format = {"type": "json_object"},
        messages        = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    )

    raw_content = response.choices[0].message.content or "{}"
    parsed      = json.loads(raw_content)
    raw_offers  = parsed.get("offers", [])

    if not isinstance(raw_offers, list):
        logger.warning(f"[{provider}] Chunk {chunk_num}: unexpected offers type {type(raw_offers)}")
        return []

    valid_offers = []
    for i, raw in enumerate(raw_offers):
        try:
            valid_offers.append(Offer(**raw))
        except Exception as e:
            logger.warning(f"[{provider}] Chunk {chunk_num}, offer {i} dropped (validation failed): {e}")

    usage = response.usage
    print(f"  [{provider}] Chunk {chunk_num} ✅  {len(valid_offers)}/{len(raw_offers)} valid offers "
          f"| tokens in:{usage.prompt_tokens} out:{usage.completion_tokens}")

    return valid_offers


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_from_page(page: dict) -> dict | None:
    """
    Chunks page markdown and runs Groq extraction on each chunk.
    Deduplicates by coupon_code + offer_title within the page.

    Args:
        page: { provider, url, scraped_at, scraped_date, markdown, char_count }

    Returns:
        {
            "source_url"  : str,
            "provider"    : str,
            "scraped_date": str,
            "offers"      : [list of offer dicts],
        }
        or None if nothing extracted.
    """
    provider = page["provider"]
    url      = page["url"]
    markdown = page["markdown"]
    client   = Groq(api_key=GROQ_API_KEY)

    chunks = _chunk_markdown(markdown)

    print(f"\n  [{provider}] Extracting from: {url}")
    print(f"  [{provider}] {len(markdown):,} chars → {len(chunks)} chunk(s) of ~{CHUNK_SIZE:,} chars "
          f"(overlap: {CHUNK_OVERLAP})")

    all_offers: list[Offer] = []

    for i, chunk in enumerate(chunks, 1):
        try:
            offers = _call_groq(chunk, client, provider, chunk_num=i)
            all_offers.extend(offers)
        except Exception as e:
            print(f"  [{provider}] Chunk {i} ❌ Failed after retries: {e}")

        if i < len(chunks):
            time.sleep(5)   # respect Groq TPM limits between chunks

    if not all_offers:
        print(f"  [{provider}] ❌ No offers extracted.")
        return None

    # Intra-page dedup by coupon_code + offer_title
    seen    = set()
    deduped = []
    for offer in all_offers:
        key = (offer.coupon_code, offer.offer_title.lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(offer)

    removed = len(all_offers) - len(deduped)
    print(f"  [{provider}] 🎉 {len(deduped)} unique offers"
          + (f" ({removed} intra-page duplicates removed)" if removed else ""))

    return {
        "source_url"  : url,
        "provider"    : provider,
        "scraped_date": page.get("scraped_date", date.today().isoformat()),
        "offers"      : [o.model_dump() for o in deduped],
    }


def extract_all(pages: list) -> list:
    """
    Runs Groq extraction on every fetched page.
    Saves per-provider raw output to output/promotions_raw_{provider}_{timestamp}.json

    Args:
        pages: list from ingestion.fetch_all()

    Returns:
        list of { source_url, provider, scraped_date, offers: [...] }
    """
    import datetime as dt
    timestamp  = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    results      = []
    total_offers = 0

    print(f"\n{'='*55}")
    print(f"  EXTRACTION STARTING — {len(pages)} page(s) | model: {GROQ_MODEL}")
    print(f"  Chunk size: {CHUNK_SIZE:,} chars | overlap: {CHUNK_OVERLAP}")
    print(f"{'='*55}")

    for i, page in enumerate(pages):
        result = extract_from_page(page)
        if result:
            results.append(result)
            total_offers += len(result["offers"])

            # Save per-provider raw output
            provider = result["provider"]
            filename = f"promotions_raw_{provider}_{timestamp}.json"
            out_path = os.path.join(OUTPUT_DIR, filename)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"  [{provider}] 💾 Raw saved → {out_path}")

        if i < len(pages) - 1:
            print(f"\n  ⏸  Inter-page cooldown (10s)...")
            time.sleep(10)

    print(f"\n{'='*55}")
    print(f"  EXTRACTION COMPLETE — {len(results)}/{len(pages)} pages | {total_offers} raw offers")
    print(f"{'='*55}\n")

    return results
