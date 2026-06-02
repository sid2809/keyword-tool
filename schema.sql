-- Bulk Keyword Research Tool — Postgres schema (spec §3)

CREATE TABLE IF NOT EXISTS keyword_cache (
    id                          BIGSERIAL PRIMARY KEY,
    keyword                     TEXT NOT NULL,
    geo_target                  TEXT NOT NULL DEFAULT 'geoTargetConstants/2840',
    language                    TEXT NOT NULL DEFAULT 'ALL',
    network                     TEXT NOT NULL DEFAULT 'GOOGLE_SEARCH',
    recent_avg_monthly_searches BIGINT,
    raw_avg_monthly_searches    BIGINT,
    competition                 TEXT,
    competition_index           INT,
    low_top_of_page_bid_micros  BIGINT,
    high_top_of_page_bid_micros BIGINT,
    three_month_change          NUMERIC,
    currency_code               TEXT,
    has_data                    BOOLEAN NOT NULL DEFAULT TRUE,
    is_close_variant_merged     BOOLEAN NOT NULL DEFAULT FALSE,
    monthly_volumes             JSONB,
    fetched_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (keyword, geo_target, language, network)
);

CREATE TABLE IF NOT EXISTS searches (
    id           BIGSERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    label        TEXT,
    tab          TEXT NOT NULL,
    input_count  INT,
    filters      JSONB,
    input_data   JSONB
);

CREATE TABLE IF NOT EXISTS shortlist (
    id               BIGSERIAL PRIMARY KEY,
    keyword          TEXT NOT NULL UNIQUE,
    added_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_tab       TEXT,
    source_search_id BIGINT REFERENCES searches(id),
    metrics_snapshot JSONB
);
