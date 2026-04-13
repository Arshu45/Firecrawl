"""
Data Transformation Layer
Maps internal MySQL schema formats into the unified Promotion schema.
"""

import json
import os
import datetime
from decimal import Decimal

from config.settings import CATEGORY_MAP, CLIENT_BRAND

def load_mapping() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'internal_mapping.json')
    with open(config_path, 'r') as f:
        return json.load(f)

def _jsonify(val):
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, str):
        stripped = val.strip()
        if stripped.lower() in {"", "null", "none", "n/a", "na", "-", "--"}:
            return None
        return stripped
    return val

def transform_internal_data(raw_rows: list[dict]) -> list[dict]:
    """
    Transforms raw MySQL dictionaries into the unified promotional schema
    ready to be upserted into internal_promotions.
    """
    config = load_mapping()
    field_maps = config["mappings"]
    value_maps = config["value_maps"]
    scraped_date = datetime.date.today().isoformat()
    
    transformed_offers = []
    
    for row in raw_rows:
        offer = {
            "source_url": "mysql://fashion_retail.promotion",
            "scraped_date": scraped_date,
            "source_count": 1,
            "description": None,
            "brand": CLIENT_BRAND,
        }
        
        # Apply field mappings
        for mysql_col, unified_field in field_maps.items():
            val = _jsonify(row.get(mysql_col))
            if val is not None:
                offer[unified_field] = val
        
        # Process Discount Values
        pct = offer.pop("discount_pct", None)
        if pct and float(pct) > 0:
            offer["discount_min"] = float(pct)
            offer["discount_max"] = float(pct)
        else:
            offer["discount_min"] = None
            offer["discount_max"] = None
            
        flat = offer.get("flat_value")
        if flat and float(flat) == 0:
            offer["flat_value"] = None
            
        min_p = offer.get("min_purchase")
        if min_p and float(min_p) == 0:
            offer["min_purchase"] = None

        # Value Enums translation
        ptype = offer.get("promo_type")
        if ptype in value_maps["promo_type"]:
            offer["promo_type"] = value_maps["promo_type"][ptype]
        else:
            offer["promo_type"] = "other"

        utype = offer.get("user_type")
        if utype in value_maps["user_type"]:
            offer["user_type"] = value_maps["user_type"][utype]
        else:
            offer["user_type"] = "all"

        # Apply category normalization if hint matches
        cat_hint = offer.pop("category_hint", None)
        offer["category"] = CATEGORY_MAP.get(str(cat_hint).lower(), "Other") if cat_hint else "Other"
        
        transformed_offers.append(offer)
        
    return transformed_offers
