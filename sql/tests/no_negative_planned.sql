-- Planned receipts are never negative or zero-sized, and releases sit exactly
-- one lead time before their receipt.
SELECT planned_id AS id, 'non-positive planned quantity' AS problem
FROM planned WHERE qty <= 0
UNION ALL
SELECT item_id || '@' || week, 'negative planned receipt' FROM net_weekly WHERE planned_receipt < 0
UNION ALL
SELECT planned_id, 'release is not receipt minus lead time'
FROM planned WHERE release_week <> receipt_week - lead_time_weeks;
