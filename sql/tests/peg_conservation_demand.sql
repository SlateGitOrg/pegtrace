-- Every demand must be pegged in full: pegged quantity = demand quantity.
SELECT d.demand_id, d.item_id, d.qty AS demand_qty, coalesce(sum(p.qty), 0) AS pegged_qty
FROM demand AS d
LEFT JOIN peg AS p ON p.demand_id = d.demand_id
GROUP BY d.demand_id, d.item_id, d.qty
HAVING coalesce(sum(p.qty), 0) <> d.qty;
