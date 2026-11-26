-- Run inside the scenario connection after base_impacted_orders has been loaded
-- with the base run's impacted orders. Lists every order whose delay or revenue
-- at risk differs between the base run and the scenario.
CREATE OR REPLACE TABLE whatif_diff AS
SELECT coalesce(s.order_id, b.order_id) AS order_id,
       coalesce(s.customer, b.customer) AS customer,
       coalesce(s.model, b.model) AS model,
       coalesce(s.due_week, b.due_week) AS due_week,
       coalesce(s.qty_at_risk, 0) AS qty_at_risk,
       coalesce(b.weeks_late, 0) AS base_weeks_late,
       coalesce(s.weeks_late, 0) AS weeks_late,
       coalesce(b.revenue_at_risk, 0) AS base_revenue_at_risk,
       coalesce(s.revenue_at_risk, 0) AS revenue_at_risk,
       coalesce(s.revenue_at_risk, 0) - coalesce(b.revenue_at_risk, 0) AS revenue_delta,
       coalesce(s.root_item, b.root_item) AS root_item,
       coalesce(s.chain, b.chain) AS chain
FROM impacted_orders AS s
FULL OUTER JOIN base_impacted_orders AS b ON b.order_id = s.order_id
WHERE coalesce(s.weeks_late, 0) <> coalesce(b.weeks_late, 0)
   OR coalesce(s.revenue_at_risk, 0) <> coalesce(b.revenue_at_risk, 0)
ORDER BY order_id;
