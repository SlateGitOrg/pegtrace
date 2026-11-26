-- LLC(child) > LLC(parent) for every BOM edge.
SELECT b.parent_id, b.child_id, lp.llc AS parent_llc, lc.llc AS child_llc
FROM bom AS b
LEFT JOIN llc AS lp ON lp.item_id = b.parent_id
LEFT JOIN llc AS lc ON lc.item_id = b.child_id
WHERE lc.llc IS NULL OR lp.llc IS NULL OR lc.llc <= lp.llc;
