-- No supply may be pegged for more than it holds, and no peg may be empty.
SELECT s.supply_id, s.item_id, s.qty AS supply_qty, coalesce(sum(p.qty), 0) AS pegged_qty
FROM supply AS s
LEFT JOIN peg AS p ON p.supply_id = s.supply_id
GROUP BY s.supply_id, s.item_id, s.qty
HAVING coalesce(sum(p.qty), 0) > s.qty
UNION ALL
SELECT supply_id, item_id, 0, qty FROM peg WHERE qty <= 0;
