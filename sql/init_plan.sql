-- Empty working tables that net_level.sql fills one low-level code at a time.
-- demand: gross requirements. need_week is the week the quantity is wanted;
-- eff_week is the week it is netted in (requirements dated before the as-of
-- week are netted in the as-of week but keep their original need_week).
CREATE OR REPLACE TABLE demand (
    demand_id VARCHAR,
    item_id VARCHAR,
    need_week INTEGER,
    eff_week INTEGER,
    qty BIGINT,
    kind VARCHAR,
    source_planned_id VARCHAR,
    parent_item_id VARCHAR,
    sales_order_id VARCHAR
);

-- planned: planned orders (lot-for-lot, one per item and receipt week).
CREATE OR REPLACE TABLE planned (
    planned_id VARCHAR,
    item_id VARCHAR,
    receipt_week INTEGER,
    release_week INTEGER,
    qty BIGINT,
    lead_time_weeks INTEGER,
    past_due BOOLEAN
);

-- net_weekly: the cumulative netting identity, one row per item and event week.
CREATE OR REPLACE TABLE net_weekly (
    item_id VARCHAR,
    week INTEGER,
    gross BIGINT,
    scheduled BIGINT,
    cum_gross BIGINT,
    cum_scheduled BIGINT,
    on_hand BIGINT,
    cum_deficit BIGINT,
    cum_planned BIGINT,
    planned_receipt BIGINT
);
