"""
MySQL Fetcher
Connects to the internal remote MySQL instance and extracts promotional data.
"""

import pymysql
import logging

logger = logging.getLogger(__name__)

# Hardcoded for the POC per user specs:
MYSQL_HOST = "172.27.133.173"
MYSQL_PORT = 3306
MYSQL_USER = "readonly_user"
MYSQL_PASS = "cybage@123"
MYSQL_DB   = "fashion_retail"

def fetch_internal_promotions() -> list[dict]:
    """
    Connects into MySQL to fetch all active promotions.
    Returns a list of dictionaries mapping directly to the DB columns.
    """
    logger.info(f"Connecting to MySQL at {MYSQL_HOST}...")

    try:
        connection = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASS,
            database=MYSQL_DB,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10
        )
    except Exception as e:
        logger.error(f"MySQL connection failed: {e}")
        raise

    try:
        with connection.cursor() as cursor:
            # Fetch all active promotions
            sql = "SELECT * FROM promotion WHERE is_active = 1"
            cursor.execute(sql)
            rows = cursor.fetchall()
            logger.info(f"Fetched {len(rows)} active promotions from MySQL.")
            
            # pymysql returns Decimals and Dates which might need string casting 
            # for easy JSON serialization later. We will just return the raw dicts
            # and let the transformer handle the formatting if needed.
            return list(rows)
    finally:
        connection.close()
