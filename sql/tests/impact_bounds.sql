-- Quantity and revenue at risk never exceed the order itself, and late quantity
-- never falls below what the pegs show.
SELECT 'order bounds' AS problem, order_id AS id, qty_at_risk AS found, qty AS limit_qty
FROM impacted_orders
WHERE qty_at_risk <= 0 OR qty_at_risk > qty OR revenue_at_risk > revenue OR weeks_late <= 0
UNION ALL
-- a demand is at least as late as the quantity pegged to supplies that arrive late
SELECT 'late quantity below own late pegs', o.demand_id, coalesce(ld.late_qty, 0), o.qty
FROM (
    SELECT demand_id, sum(qty) AS qty
    FROM peg
    WHERE weeks_late > 0 AND avail_week > greatest(need_week, getvariable('as_of_week')::INTEGER)
    GROUP BY demand_id
) AS o
LEFT JOIN late_demand AS ld ON ld.demand_id = o.demand_id
WHERE coalesce(ld.late_qty, 0) < o.qty - 1e-6
UNION ALL
-- a planned order's pegs are at least as late as its worst child demand
SELECT 'late share lost on the way up', up.demand_id, coalesce(u.late_qty, 0),
       up.qty * c.late_qty / c.qty
FROM late_demand AS c
JOIN peg AS up ON up.supply_id = c.source_planned_id
LEFT JOIN late_demand AS u ON u.demand_id = up.demand_id
WHERE coalesce(u.late_qty, 0) < up.qty * c.late_qty / c.qty - 1e-6;
