-- =============================================================
-- Promotion Intelligence — Database Schema
-- Run once: psql -d promo_db_v1 -f database/schema.sql
-- Safe to re-run (all CREATE statements use IF NOT EXISTS)
-- =============================================================


-- ── Competitors ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS competitors (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(100) UNIQUE NOT NULL,
    source_url   TEXT,
    added_date   DATE DEFAULT CURRENT_DATE
);


-- ── Promotions ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS promotions (
    id            SERIAL PRIMARY KEY,
    competitor_id INT REFERENCES competitors(id),
    offer_title   TEXT NOT NULL,
    description   TEXT,
    brand         VARCHAR(100),
    category      VARCHAR(50),
    promo_type    VARCHAR(50),
    discount_min  NUMERIC(5,2),
    discount_max  NUMERIC(5,2),
    flat_value    NUMERIC(10,2),
    min_purchase  NUMERIC(10,2),
    coupon_code   VARCHAR(100),
    user_type     VARCHAR(20)  DEFAULT 'all',
    valid_until   VARCHAR(50),
    source_count  INT          DEFAULT 1,
    source_url    TEXT,
    scraped_date  DATE         DEFAULT CURRENT_DATE,
    created_at    TIMESTAMP    DEFAULT NOW()
);


-- ── Internal Pricing (Westside baseline — populated manually) ─
CREATE TABLE IF NOT EXISTS internal_pricing (
    id           SERIAL PRIMARY KEY,
    category     VARCHAR(50) UNIQUE NOT NULL,
    our_discount NUMERIC(5,2) DEFAULT 0,
    margin       NUMERIC(5,2),
    updated_at   TIMESTAMP DEFAULT NOW()
);


-- ── Indexes for common query patterns ────────────────────────
CREATE INDEX IF NOT EXISTS idx_promotions_competitor   ON promotions(competitor_id);
CREATE INDEX IF NOT EXISTS idx_promotions_category     ON promotions(category);
CREATE INDEX IF NOT EXISTS idx_promotions_scraped_date ON promotions(scraped_date);
CREATE INDEX IF NOT EXISTS idx_promotions_coupon_code  ON promotions(coupon_code);
CREATE INDEX IF NOT EXISTS idx_promotions_promo_type   ON promotions(promo_type);


-- ── Seed internal_pricing with default categories ─────────────
INSERT INTO internal_pricing (category, our_discount, margin)
VALUES
    ('Fashion',     0, 40),
    ('Footwear',    0, 38),
    ('Beauty',      0, 45),
    ('Electronics', 0, 20),
    ('Home',        0, 35),
    ('Sports',      0, 40),
    ('Jewellery',   0, 50),
    ('Other',       0, 30)
ON CONFLICT (category) DO NOTHING;
