-- FIFO pegging, item by item, by interval overlap on the cumulative-quantity axis.
-- Demand is laid end to end ordered by need week; supply is laid end to end
-- ordered by effective availability. Every overlap of a demand interval and a
-- supply interval is one peg row.
--   on hand            available in the as-of week
--   scheduled receipt  available in its due week (an overdue one: the as-of week)
--   planned order      available at max(receipt week, as-of week + lead time)
-- weeks_late = max(0, availability - need week), measured against the original
-- need week even when the requirement was netted in the as-of week.
CREATE OR REPLACE TABLE supply AS
SELECT 'OH-' || item_id AS supply_id, item_id, 'on_hand' AS kind, 0 AS kind_rank,
       qty::BIGINT AS qty, getvariable('as_of_week')::INTEGER AS avail_week
FROM on_hand
WHERE qty > 0
UNION ALL
SELECT receipt_id, item_id, 'scheduled', 1, qty::BIGINT,
       greatest(due_week, getvariable('as_of_week')::INTEGER)
FROM scheduled_receipts
UNION ALL
SELECT planned_id, item_id, 'planned', 2, qty,
       greatest(receipt_week, getvariable('as_of_week')::INTEGER + lead_time_weeks)
FROM planned;

CREATE OR REPLACE TABLE supply_ranges AS
SELECT *,
       sum(qty) OVER w - qty AS s_start,
       sum(qty) OVER w AS s_end
FROM supply
WINDOW w AS (PARTITION BY item_id ORDER BY avail_week, kind_rank, supply_id
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

CREATE OR REPLACE TABLE demand_ranges AS
SELECT *,
       sum(qty) OVER w - qty AS d_start,
       sum(qty) OVER w AS d_end
FROM demand
WINDOW w AS (PARTITION BY item_id ORDER BY need_week, demand_id
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

CREATE OR REPLACE TABLE peg AS
SELECT d.item_id, d.demand_id, s.supply_id, s.kind AS supply_kind,
       (least(d.d_end, s.s_end) - greatest(d.d_start, s.s_start))::BIGINT AS qty,
       d.need_week, s.avail_week,
       greatest(0, s.avail_week - d.need_week)::INTEGER AS weeks_late
FROM demand_ranges AS d
JOIN supply_ranges AS s
  ON s.item_id = d.item_id AND d.d_start < s.s_end AND s.s_start < d.d_end;

-- Planned orders nothing is pegged to (or only partly): cancel or reduce candidates.
CREATE OR REPLACE TABLE unpegged_planned AS
SELECT p.planned_id, p.item_id, p.receipt_week, p.release_week, p.qty,
       p.qty - coalesce(sum(g.qty), 0)::BIGINT AS unpegged_qty,
       CASE WHEN coalesce(sum(g.qty), 0) = 0 THEN 'cancel' ELSE 'reduce' END AS suggestion
FROM planned AS p
LEFT JOIN peg AS g ON g.supply_id = p.planned_id
GROUP BY p.planned_id, p.item_id, p.receipt_week, p.release_week, p.qty
HAVING p.qty - coalesce(sum(g.qty), 0) > 0;
