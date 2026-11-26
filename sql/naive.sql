-- Baseline that nets stock separately on every usage of an item, the way a
-- per-path spreadsheet explosion does. Each usage (a parent item, or direct
-- customer orders) nets the item's whole stock and open receipts on its own, so
-- shared stock is counted once per usage. The low-level-code result is the sum
-- of the planned order quantities. The per-path figure is the sum of each usage's
-- own shortfall. Only items with two or more usages are listed.
CREATE OR REPLACE TABLE netting_comparison AS
WITH usage AS (
    SELECT item_id, coalesce(parent_item_id, 'SALES') AS usage_id, sum(qty) AS gross
    FROM demand
    GROUP BY item_id, coalesce(parent_item_id, 'SALES')
),
stock AS (
    SELECT i.item_id,
           coalesce(oh.qty, 0)::BIGINT AS on_hand,
           coalesce(sr.qty, 0)::BIGINT AS open_receipts
    FROM items AS i
    LEFT JOIN on_hand AS oh ON oh.item_id = i.item_id
    LEFT JOIN (SELECT item_id, sum(qty) AS qty FROM scheduled_receipts GROUP BY item_id) AS sr
      ON sr.item_id = i.item_id
),
per_path AS (
    SELECT u.item_id, count(*) AS usages, sum(u.gross)::BIGINT AS gross_total,
           sum(greatest(0, u.gross - s.on_hand - s.open_receipts))::BIGINT AS per_path_net
    FROM usage AS u
    JOIN stock AS s ON s.item_id = u.item_id
    GROUP BY u.item_id
    HAVING count(*) >= 2
),
level_net AS (
    SELECT item_id, sum(qty)::BIGINT AS llc_net FROM planned GROUP BY item_id
)
SELECT p.item_id, l.llc, p.usages, p.gross_total, s.on_hand, s.open_receipts,
       coalesce(n.llc_net, 0)::BIGINT AS llc_net, p.per_path_net
FROM per_path AS p
JOIN stock AS s ON s.item_id = p.item_id
JOIN llc AS l ON l.item_id = p.item_id
LEFT JOIN level_net AS n ON n.item_id = p.item_id
ORDER BY p.item_id;
