-- Returns one row per cycle in the bill of materials, written as an arrow path
-- that starts and ends on the same item, e.g. "SUB-A -> SUB-B -> SUB-A".
-- Every item is tried as a start, so cycles that no end item reaches are found
-- too. A cycle is reported once, from its alphabetically first item.
WITH RECURSIVE walk(start_id, node_id, path) AS (
    SELECT item_id, item_id, [item_id]
    FROM items
    UNION ALL
    SELECT w.start_id, b.child_id, list_append(w.path, b.child_id)
    FROM walk AS w
    JOIN bom AS b ON b.parent_id = w.node_id
    WHERE (w.node_id <> w.start_id OR len(w.path) = 1)
      AND (b.child_id = w.start_id OR NOT list_contains(w.path, b.child_id))
)
SELECT array_to_string(path, ' -> ') AS cycle_path
FROM walk
WHERE len(path) > 1
  AND node_id = start_id
  AND start_id = list_min(path)
ORDER BY cycle_path;
