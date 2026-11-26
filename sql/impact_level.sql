-- Impact, part 2: how much of each demand is late, for the items whose low-level
-- code equals getvariable('llc'). The runner calls it from the deepest code up to
-- 0, so the late share of every planned order's children is known before the
-- planned order itself is looked at.
--
-- A peg is late for its whole quantity when its own supply arrives late (same
-- anchor rule as impact.sql). Otherwise a peg to a planned order inherits that
-- order's late share: the order is as late as its worst child.
--   late share of a planned order = max over its child demands (parallel
--                                   components cover the same units)
--   late quantity of a demand      = sum over its pegs (different supplies cover
--                                   different units)
-- The max is taken across children, the sum across the pegs of one demand.
INSERT INTO late_demand
WITH order_share AS (
    SELECT source_planned_id AS planned_id, max(late_qty / qty) AS late_share
    FROM late_demand
    WHERE source_planned_id IS NOT NULL
    GROUP BY source_planned_id
)
SELECT d.demand_id, d.item_id, d.source_planned_id, d.sales_order_id, d.qty,
       sum(CASE
               WHEN p.weeks_late > 0
                AND p.avail_week > greatest(p.need_week, getvariable('as_of_week')::INTEGER)
                   THEN p.qty
               ELSE p.qty * coalesce(s.late_share, 0)
           END) AS late_qty
FROM demand AS d
JOIN llc AS l ON l.item_id = d.item_id AND l.llc = getvariable('llc')::INTEGER
JOIN peg AS p ON p.demand_id = d.demand_id
LEFT JOIN order_share AS s ON s.planned_id = p.supply_id
GROUP BY d.demand_id, d.item_id, d.source_planned_id, d.sales_order_id, d.qty
HAVING sum(CASE
               WHEN p.weeks_late > 0
                AND p.avail_week > greatest(p.need_week, getvariable('as_of_week')::INTEGER)
                   THEN p.qty
               ELSE p.qty * coalesce(s.late_share, 0)
           END) > 0;
