"""
All LLM prompts live here. Never inline prompts in engine files.
"""

# ── Layer 1: Extraction ────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """\
You are a precise retail promotion data extraction assistant.
Your job is to extract promotional offers from coupon/deal website content.
You MUST return a valid JSON object with a single key "offers" containing an array of offer objects.
Example: {"offers": [{...}, {...}]}
If you find no offers, return: {"offers": []}
"""

EXTRACTION_USER_PROMPT = """\
Extract EVERY promotional offer, coupon, and deal from the markdown below.
This is a chunk of a larger page — extract ALL offers you find in this section.

Return a JSON object: {{"offers": [list of offer objects]}}

For each offer extract these exact fields:
- offer_title  : exact main headline of the offer (string, required)
- description  : full offer description (string or null)
- brand        : specific brand name if mentioned, else null
- category     : one of: Fashion / Footwear / Beauty / Electronics / Home / Sports / Jewellery / Other
- promo_type   : one of: percentage | flat | bogo | bundle | free_delivery | other
- discount_min : lowest discount % as number (e.g. 50 from "50-80% Off"), null if not applicable
- discount_max : highest discount % as number (e.g. 80 from "50-80% Off"), null if not applicable
- flat_value   : flat rupee discount as number (e.g. 300 from "Rs 300 Off"), null if not present
- min_purchase : minimum purchase amount as number (e.g. 1999 from "orders above Rs 1999"), null if not mentioned
- coupon_code  : exact coupon or promo code string if present, null if none
- user_type    : "new" if only new users, "existing" if existing users only, "all" otherwise
- valid_until  : expiry date string if mentioned (e.g. "31 March 2026"), null if not mentioned

Rules:
- Extract EVERY offer. Do not summarise or skip.
- If discount range is "up to 80%", set discount_max=80, discount_min=null
- If exact discount is "50% off", set both discount_min and discount_max to 50
- Only extract actual promotional deals. Ignore nav, login popups, testimonials, footer.

--- MARKDOWN START ---
{markdown_chunk}
--- MARKDOWN END ---
"""


# ── Layer 4: Insights Narration ────────────────────────────────────────────────

