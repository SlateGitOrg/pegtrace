-- Nets every item whose low-level code equals getvariable('llc').
-- Variables set by the runner: as_of_week, llc. Lot-for-lot: a planned receipt
-- covers exactly the shortfall of its week, no lot sizing, no safety stock.

-- 1. Gross requirements from customer orders.
INSERT INTO demand
SELECT s.order_id, s.item_id, s.due_week,
       greatest(s.due_week, getvariable('as_of_week')::INTEGER),
       s.qty, 'sales', NULL, NULL, s.order_id
FROM sales_orders AS s
JOIN llc AS l ON l.item_id = s.item_id AND l.llc = getvariable('llc')::INTEGER;

-- 2. Dependent demand: each parent's planned release needs qty_per children per
--    unit, grossed up for the parent's scrap and rounded up. It is dated at the
--    parent's release week. Every parent has a lower code, so it is planned already.
INSERT INTO demand
SELECT p.planned_id || '>' || b.child_id, b.child_id, p.release_week,
       greatest(p.release_week, getvariable('as_of_week')::INTEGER),
       ceil(round(b.qty_per * p.qty / (1 - pi.scrap_pct / 100.0), 6))::BIGINT,
       'dependent', p.planned_id, p.item_id, NULL
FROM planned AS p
JOIN bom AS b ON b.parent_id = p.item_id
JOIN items AS pi ON pi.item_id = p.item_id
JOIN llc AS l ON l.item_id = b.child_id AND l.llc = getvariable('llc')::INTEGER;

-- 3. Netting with window functions.
--    cumulative deficit  D(t) = cum gross(t) - on hand - cum scheduled receipts(t)
--    cumulative planned  P(t) = max(0, running maximum of D)
--    planned receipt(t)  = P(t) - P(t-1)
--    Scheduled receipts due before the as-of week arrive in the as-of week.
INSERT INTO net_weekly
WITH level_items AS (
    SELECT item_id FROM llc WHERE llc = getvariable('llc')::INTEGER
),
gross AS (
    SELECT item_id, eff_week AS week, sum(qty)::BIGINT AS gross
    FROM demand
    WHERE item_id IN (SELECT item_id FROM level_items)
    GROUP BY item_id, eff_week
),
receipts AS (
    SELECT item_id, greatest(due_week, getvariable('as_of_week')::INTEGER) AS week,
           sum(qty)::BIGINT AS scheduled
    FROM scheduled_receipts
    WHERE item_id IN (SELECT item_id FROM level_items)
    GROUP BY item_id, greatest(due_week, getvariable('as_of_week')::INTEGER)
),
event_weeks AS (
    SELECT item_id, week FROM gross
    UNION
    SELECT item_id, week FROM receipts
),
joined AS (
    SELECT e.item_id, e.week,
           coalesce(g.gross, 0) AS gross,
           coalesce(r.scheduled, 0) AS scheduled,
           coalesce(oh.qty, 0)::BIGINT AS on_hand
    FROM event_weeks AS e
    LEFT JOIN gross AS g USING (item_id, week)
    LEFT JOIN receipts AS r USING (item_id, week)
    LEFT JOIN on_hand AS oh ON oh.item_id = e.item_id
),
cumulative AS (
    SELECT *,
           sum(gross) OVER w AS cum_gross,
           sum(scheduled) OVER w AS cum_scheduled
    FROM joined
    WINDOW w AS (PARTITION BY item_id ORDER BY week
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
deficit AS (
    SELECT *, cum_gross - on_hand - cum_scheduled AS cum_deficit FROM cumulative
),
running AS (
    SELECT *,
           greatest(0, max(cum_deficit) OVER (
               PARTITION BY item_id ORDER BY week
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))::BIGINT AS cum_planned
    FROM deficit
)
SELECT item_id, week, gross, scheduled, cum_gross::BIGINT, cum_scheduled::BIGINT, on_hand,
       cum_deficit::BIGINT, cum_planned,
       cum_planned - coalesce(lag(cum_planned) OVER (PARTITION BY item_id ORDER BY week), 0)
           AS planned_receipt
FROM running;

-- 4. Planned orders. A release before the as-of week is past due.
INSERT INTO planned
SELECT 'PL-' || n.item_id || '-' || n.week, n.item_id, n.week,
       n.week - i.lead_time_weeks, n.planned_receipt, i.lead_time_weeks,
       n.week - i.lead_time_weeks < getvariable('as_of_week')::INTEGER
FROM net_weekly AS n
JOIN items AS i ON i.item_id = n.item_id
JOIN llc AS l ON l.item_id = n.item_id AND l.llc = getvariable('llc')::INTEGER
WHERE n.planned_receipt > 0;
