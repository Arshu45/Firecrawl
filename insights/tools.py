import json
import logging

from langchain_core.tools import tool

from database.db_client import DBClient

logger = logging.getLogger(__name__)


def _truncate(value, limit: int = 500) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"

@tool
def get_category_trends(category: str) -> str:
    """
    Use this only when a specific category is explicitly known from the user request.
    Returns average discounts for both Westside (internal) and external competitors for that exact category.
    """
    category = category.strip().title()
    logger.info("Tool get_category_trends called | category=%s", category)
    query = """
    SELECT 
        'Westside' as brand, 
        ROUND(AVG(discount_max), 2) as avg_discount, 
        COUNT(*) as active_offers
    FROM internal_promotions
    WHERE category = %s AND valid_until >= CURRENT_DATE::text AND discount_max IS NOT NULL
    
    UNION ALL
    
    SELECT 
        c.name as brand, 
        ROUND(AVG(p.discount_max), 2) as avg_discount, 
        COUNT(p.id) as active_offers
    FROM promotions p
    JOIN competitors c ON p.competitor_id = c.id
    WHERE p.category = %s AND p.discount_max IS NOT NULL
    GROUP BY c.name
    """
    
    with DBClient() as db:
        rows = db.execute(query, (category, category))
    logger.info(
        "Tool get_category_trends DB rows fetched | category=%s | row_count=%d | preview=%s",
        category,
        len(rows),
        _truncate(rows),
    )
    
    if not rows:
        return f"No active promotional data found for category: {category}."
        
    result = json.dumps(rows, default=str)
    logger.info("Tool get_category_trends returning | payload=%s", _truncate(result))
    return result


@tool
def get_top_competitors(category: str) -> str:
    """
    Use this only when a specific category is explicitly known from the user request.
    Returns which competitors are giving the deepest discounts in that exact category.
    """
    category = category.strip().title()
    logger.info("Tool get_top_competitors called | category=%s", category)
    query = """
    SELECT 
        c.name as competitor, 
        MAX(p.discount_max) as deepest_discount,
        ROUND(AVG(p.discount_max), 2) as avg_discount
    FROM promotions p
    JOIN competitors c ON p.competitor_id = c.id
    WHERE p.category = %s AND p.discount_max IS NOT NULL
    GROUP BY c.name
    ORDER BY deepest_discount DESC
    LIMIT 5
    """
    
    with DBClient() as db:
        rows = db.execute(query, (category,))
    logger.info(
        "Tool get_top_competitors DB rows fetched | category=%s | row_count=%d | preview=%s",
        category,
        len(rows),
        _truncate(rows),
    )
    
    if not rows:
        return f"No competitor discounts found for category: {category}."
        
    result = json.dumps(rows, default=str)
    logger.info("Tool get_top_competitors returning | payload=%s", _truncate(result))
    return result


@tool
def get_active_offers(brand: str, limit: int = 5) -> str:
    """
    Use this only when the user explicitly asks for the exact offers of a specific brand.
    Do not use it for general category comparisons unless the same brand is already the focus.
    """
    brand = brand.strip()
    logger.info("Tool get_active_offers called | brand=%s | limit=%s", brand, limit)
    
    if brand.lower() == 'westside':
        query = """
        SELECT offer_title, category, promo_type, discount_max, valid_until
        FROM internal_promotions
        WHERE valid_until >= CURRENT_DATE::text
        ORDER BY discount_max DESC NULLS LAST
        LIMIT %s
        """
        params = (limit,)
    else:
        query = """
        SELECT p.offer_title, p.category, p.promo_type, p.discount_max
        FROM promotions p
        JOIN competitors c ON p.competitor_id = c.id
        WHERE c.name ILIKE %s
        ORDER BY p.discount_max DESC NULLS LAST
        LIMIT %s
        """
        params = (brand, limit)
        
    with DBClient() as db:
        rows = db.execute(query, params)
    logger.info(
        "Tool get_active_offers DB rows fetched | brand=%s | row_count=%d | preview=%s",
        brand,
        len(rows),
        _truncate(rows),
    )
        
    if not rows:
        return f"No active offers found for brand: {brand}."

    result = json.dumps(rows, default=str)
    logger.info("Tool get_active_offers returning | payload=%s", _truncate(result))
    return result
