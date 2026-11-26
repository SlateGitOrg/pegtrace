-- After planned receipts, projected stock is never below zero in any netted week.
SELECT item_id, week, on_hand + cum_scheduled + cum_planned - cum_gross AS projected_balance
FROM net_weekly
WHERE on_hand + cum_scheduled + cum_planned - cum_gross < 0;
