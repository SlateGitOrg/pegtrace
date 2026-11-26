-- Impact, part 1: walk late pegs upward to the customer orders they will make late.
-- Anchor: a late peg that is not merely inherited. A peg whose need week
-- predates the as-of week and whose supply is available in the as-of week is
-- late only because the parent's release is already past due; the parent's own
-- late peg carries that, so it is not a root cause.
-- Step: child demand -> the parent planned order it belongs to -> that planned
-- order's pegs (the demands it serves). Stop at a sales demand.
-- The walk gives the root cause, the chain text and the delay in weeks (the
-- maximum over paths: lead times are already built into the need weeks, so a
-- child that is late by w weeks makes every order above it late by w weeks).
-- How much of an order is late is not decided here: several paths can cover the
-- same units or different ones, so quantities come from impact_level.sql.
CREATE OR REPLACE TABLE impact_paths AS
WITH RECURSIVE walk(root_item, cur_demand, weeks_late, chain) AS (
    SELECT p.item_id, p.demand_id, p.weeks_late, [p.item_id]
    FROM peg AS p
    WHERE p.weeks_late > 0
      AND p.avail_week > greatest(p.need_week, getvariable('as_of_week')::INTEGER)
    UNION ALL
    SELECT w.root_item, up.demand_id, w.weeks_late, list_append(w.chain, d.parent_item_id)
    FROM walk AS w
    JOIN demand AS d ON d.demand_id = w.cur_demand AND d.kind = 'dependent'
    JOIN peg AS up ON up.supply_id = d.source_planned_id
)
SELECT DISTINCT d.sales_order_id AS order_id, w.root_item, w.weeks_late, w.chain
FROM walk AS w
JOIN demand AS d ON d.demand_id = w.cur_demand AND d.kind = 'sales';

-- Late quantity per demand, filled one low-level code at a time by impact_level.sql.
CREATE OR REPLACE TABLE late_demand (
    demand_id VARCHAR,
    item_id VARCHAR,
    source_planned_id VARCHAR,
    sales_order_id VARCHAR,
    qty BIGINT,
    late_qty DOUBLE
);
