"""
Layer 1 — AI Extraction
Converts markdown -> structured, Pydantic-validated Offer objects via Groq.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

from groq import Groq
from pydantic import BaseModel, ValidationError, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import (
    GROQ_API_KEY, GROQ_MODEL, GROQ_TEMPERATURE, GROQ_MAX_TOKENS,
    CHUNK_SIZE, CHUNK_OVERLAP, OUTPUT_DIR,
)
from extraction.prompt_templates import EXTRACTION_PROMPT

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ── Pydantic Offer schema ──────────────────────────────────────────────────

class Offer(BaseModel):
    offer_title  : str
    description  : Optional[str]  = None
    brand        : Optional[str]  = None
    category     : Optional[str]  = None
    promo_type   : str            = "other"
    discount_min : Optional[float] = None
    discount_max : Optional[float] = None
    flat_value   : Optional[float] = None
    min_purchase  : Optional[float] = None
    coupon_code  : Optional[str]  = None
    user_type    : str            = "all"
    valid_until  : Optional[str]  = None

    @field_validator("promo_type")
    @classmethod
    def normalise_promo_type(cls, v: str) -> str:
        mapping = {
            "percentage_range": "percentage",
            "price_point"     : "flat",
            "flat_amount"     : "flat",
        }
        return mapping.get(v.lower(), v.lower())

    @field_validator("user_type")
    @classmethod
    def normalise_user_type(cls, v: str) -> str:
        mapping = {
            "new_user"      : "new",
            "existing_user" : "existing",
        }
        return mapping.get(v.lower(), v.lower() if v else "all")


# ── Chunking ───────────────────────────────────────────────────────────────

def _chunk_markdown(markdown: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Splits markdown into overlapping chunks of ~`size` characters.
    Splits on blank-line boundaries to avoid cutting an offer in half.
    """
    paragraphs  = markdown.split("\n\n")
    chunks      = []
    current     = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for \\n\\n separator
        if current_len + para_len > size and current:
            chunks.append("\n\n".join(current))
            # Overlap: keep the last paragraph(s) that fit within `overlap` chars
            tail     = []
            tail_len = 0
            for p in reversed(current):
                if tail_len + len(p) + 2 <= overlap:
                    tail.insert(0, p)
                    tail_len += len(p) + 2
                else:
                    break
            current     = tail + [para]
            current_len = tail_len + para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


# ── Rate limit helpers ────────────────────────────────────────────────────

class DailyLimitExceeded(Exception):
    """Raised when Groq's daily token quota (TPD) is exhausted."""


def _is_daily_limit(exc: Exception) -> bool:
    """Distinguishes TPD (tokens per day) from TPM (tokens per minute)."""
    msg = str(exc).lower()
    return ("tokens per day" in msg or "tpd" in msg) and "429" in msg


def _is_minute_limit(exc: Exception) -> bool:
    """Transient per-minute rate limit — worth retrying after a pause."""
    msg = str(exc).lower()
    return "429" in msg and not _is_daily_limit(exc)


# ── Groq call with tenacity ────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=5, max=60),
    reraise=True,
)
def _call_groq(client: Groq, chunk: str, provider: str, chunk_num: int) -> list[dict]:
    """Single chunk → Groq → list of raw offer dicts.

    - TPD (daily quota exhausted): raises DailyLimitExceeded immediately — no retries.
    - TPM (per-minute limit):       tenacity retries up to 3×.
    - Other errors:                 tenacity retries up to 3×.
    """
    prompt = EXTRACTION_PROMPT.format(markdown_chunk=chunk)

    try:
        response = client.chat.completions.create(
            model           = GROQ_MODEL,
            temperature     = GROQ_TEMPERATURE,
            max_tokens      = GROQ_MAX_TOKENS,
            response_format = {"type": "json_object"},  # guarantees valid JSON always
            messages        = [{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        if _is_daily_limit(exc):
            logger.warning(
                "[%s] Daily token limit (TPD) reached — "
                "skipping all remaining chunks. Try again tomorrow.",
                provider,
            )
            raise DailyLimitExceeded(str(exc)) from exc
        raise   # let tenacity handle TPM and other transient errors

    raw    = response.choices[0].message.content or '{"offers": []}'
    parsed = json.loads(raw)  # always valid JSON — guaranteed by json_object mode

    # Extract the offers list from the {"offers": [...]} wrapper
    if isinstance(parsed, dict):
        offers = parsed.get("offers", [])
    elif isinstance(parsed, list):
        offers = parsed  # fallback: model returned bare array
    else:
        offers = []

    logger.info(
        "[%s] Chunk %d: %d offers | tokens in:%d out:%d",
        provider, chunk_num, len(offers),
        response.usage.prompt_tokens, response.usage.completion_tokens,
    )
    return offers


# ── Pydantic validation ────────────────────────────────────────────────────

def _validate_offers(raw_offers: list[dict], provider: str) -> list[Offer]:
    """Validate each raw dict against Offer schema. Drop invalid, log them."""
    valid   = []
    dropped = 0
    for raw in raw_offers:
        try:
            offer = Offer(**raw)
            valid.append(offer)
        except (ValidationError, TypeError) as e:
            logger.warning(f"[{provider}] Dropped invalid offer: {e} | data: {raw}")
            dropped += 1
    if dropped:
        logger.info(f"[{provider}] {dropped} offers dropped due to validation errors")
    return valid


# ── Public API ─────────────────────────────────────────────────────────────

def extract_offers(page: dict) -> dict:
    """
    Chunks page markdown and calls Groq on each chunk.
    Validates each offer with Pydantic. Dedupes by coupon_code + title.

    Args:
        page: { provider, url, scraped_at, markdown, char_count }

    Returns:
        {
          "provider"   : str,
          "source_url" : str,
          "scraped_at" : str,
          "offers"     : [list of Offer dicts],
          "total_offers": int,
        }
    """
    provider = page["provider"]
    markdown = page["markdown"]
    client   = Groq(api_key=GROQ_API_KEY)

    chunks = _chunk_markdown(markdown)
    logger.info(
        f"[{provider}] Extracting — {len(markdown):,} chars → "
        f"{len(chunks)} chunk(s) of ~{CHUNK_SIZE:,} chars"
    )

    all_raw: list[dict] = []
    daily_limit_hit = False

    for i, chunk in enumerate(chunks, 1):
        try:
            raw = _call_groq(client, chunk, provider, i)
            all_raw.extend(raw)
        except DailyLimitExceeded:
            # Quota exhausted — no point trying further chunks
            logger.warning(
                "[%s] Stopping extraction at chunk %d/%d — daily quota exhausted.",
                provider, i, len(chunks),
            )
            daily_limit_hit = True
            break
        except Exception as e:
            logger.error("[%s] Chunk %d failed after retries: %s", provider, i, e)

        if i < len(chunks) and not daily_limit_hit:
            time.sleep(5)  # respect TPM limits

    # Validate
    valid_offers = _validate_offers(all_raw, provider)

    # Deduplicate by coupon_code + title
    seen:   set  = set()
    deduped: list = []
    for offer in valid_offers:
        key = (offer.coupon_code, offer.offer_title.lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(offer)

    removed = len(valid_offers) - len(deduped)
    if removed:
        logger.info(f"[{provider}] {removed} intra-page duplicates removed")

    logger.info(f"[{provider}] Extraction complete — {len(deduped)} unique offers")

    # Serialise to dicts for downstream layers
    offers_dicts = [o.model_dump() for o in deduped]

    result = {
        "provider"    : provider,
        "source_url"  : page.get("url", ""),
        "scraped_at"  : page.get("scraped_at", ""),
        "offers"      : offers_dicts,
        "total_offers": len(offers_dicts),
    }

    # Save to output/
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts       = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"promotions_raw_{provider}_{ts}.json"
    path     = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info(f"[{provider}] Raw extractions saved → {path}")

    return result


def extract_all(pages: list[dict]) -> list[dict]:
    """Run extract_offers on every fetched page. Returns list of results."""
    results      = []
    total_offers = 0

    for i, page in enumerate(pages):
        provider = page.get("provider", "?")
        result   = extract_offers(page)
        results.append(result)
        total_offers += result["total_offers"]

        if i < len(pages) - 1:
            logger.info("Inter-page cooldown (10s)...")
            time.sleep(10)

    logger.info(
        f"Extraction complete — {len(results)} pages | {total_offers} total offers"
    )
    return results
