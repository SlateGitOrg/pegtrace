-- Explodes every end item (an item that is nobody's child) through the bill of
-- materials. One row per BOM path: the path list, the depth (0 = the end item
-- itself) and the quantity of this item per end item, before scrap.
-- The path list is also the cycle guard: a child already on the path is not
-- followed, so a cyclic BOM cannot recurse forever.
CREATE OR REPLACE TABLE explosion AS
WITH RECURSIVE ex(end_item, item_id, level, path, qty_per_end) AS (
    SELECT i.item_id, i.item_id, 0, [i.item_id], 1::BIGINT
    FROM items AS i
    WHERE NOT EXISTS (SELECT 1 FROM bom AS b WHERE b.child_id = i.item_id)
    UNION ALL
    SELECT e.end_item, b.child_id, e.level + 1, list_append(e.path, b.child_id),
           e.qty_per_end * b.qty_per
    FROM ex AS e
    JOIN bom AS b ON b.parent_id = e.item_id
    WHERE NOT list_contains(e.path, b.child_id)
)
SELECT end_item, item_id, level, path, array_to_string(path, ' > ') AS path_text, qty_per_end
FROM ex;
