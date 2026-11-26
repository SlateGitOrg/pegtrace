-- Impact, part 3: one row per impacted sales order.
-- Quantity at risk is the late quantity of the order's demand; revenue at risk is
-- pro rata. Weeks late is the maximum over the walked paths; the root cause and
-- chain are those of the longest path.
CREATE OR REPLACE TABLE impacted_orders AS
WITH worst AS (
    SELECT order_id, root_item, chain,
           row_number() OVER (
               PARTITION BY order_id
               ORDER BY weeks_late DESC, root_item, array_to_string(chain, ' <- ')
           ) AS rn
    FROM impact_paths
),
longest AS (
    SELECT order_id, max(weeks_late) AS weeks_late FROM impact_paths GROUP BY order_id
)
SELECT s.order_id, s.customer, s.item_id AS model, s.due_week, s.qty,
       round(least(ld.late_qty, s.qty), 4) AS qty_at_risk,
       lg.weeks_late::INTEGER AS weeks_late,
       s.revenue,
       round(s.revenue * least(ld.late_qty, s.qty) / s.qty, 2) AS revenue_at_risk,
       w.root_item,
       s.order_id || ' <- ' || array_to_string(list_reverse(w.chain), ' <- ') AS chain
FROM late_demand AS ld
JOIN sales_orders AS s ON s.order_id = ld.sales_order_id
JOIN longest AS lg ON lg.order_id = s.order_id
JOIN worst AS w ON w.order_id = s.order_id AND w.rn = 1
ORDER BY lg.weeks_late DESC, s.order_id;
