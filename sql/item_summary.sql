-- One row of planning facts for the item in getvariable('item'). The per-path
-- columns are filled only for items with two or more usages.
SELECT i.item_id, i.make_buy, i.lead_time_weeks, i.scrap_pct, l.llc,
       coalesce(oh.qty, 0)::BIGINT AS on_hand,
       coalesce(sr.qty, 0)::BIGINT AS open_receipts,
       coalesce(d.qty, 0)::BIGINT AS gross_requirements,
       coalesce(pl.qty, 0)::BIGINT AS llc_net_requirement,
       nc.usages, nc.per_path_net
FROM items AS i
JOIN llc AS l ON l.item_id = i.item_id
LEFT JOIN on_hand AS oh ON oh.item_id = i.item_id
LEFT JOIN (SELECT item_id, sum(qty) AS qty FROM scheduled_receipts GROUP BY item_id) AS sr
  ON sr.item_id = i.item_id
LEFT JOIN (SELECT item_id, sum(qty) AS qty FROM demand GROUP BY item_id) AS d
  ON d.item_id = i.item_id
LEFT JOIN (SELECT item_id, sum(qty) AS qty FROM planned GROUP BY item_id) AS pl
  ON pl.item_id = i.item_id
LEFT JOIN netting_comparison AS nc ON nc.item_id = i.item_id
WHERE i.item_id = getvariable('item')::VARCHAR;
