-- Orders put late through one item (getvariable('item')): every order with an
-- impact path that passes through the item, with the chain of its longest such path.
WITH through AS (
    SELECT order_id, chain, weeks_late,
           row_number() OVER (
               PARTITION BY order_id
               ORDER BY weeks_late DESC, array_to_string(chain, ' <- ')
           ) AS rn
    FROM impact_paths
    WHERE list_contains(chain, getvariable('item')::VARCHAR)
)
SELECT o.order_id, o.customer, o.model, o.due_week, o.qty_at_risk, o.weeks_late,
       o.revenue_at_risk,
       o.order_id || ' <- ' || array_to_string(list_reverse(t.chain), ' <- ') AS chain
FROM through AS t
JOIN impacted_orders AS o ON o.order_id = t.order_id
WHERE t.rn = 1
ORDER BY o.weeks_late DESC, o.order_id;
