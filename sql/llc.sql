-- Low-level code: the maximum depth at which an item appears in any explosion.
-- Netting an item at its low-level code means every parent that uses it has
-- already been planned, so all of its demand is netted together exactly once.
CREATE OR REPLACE TABLE llc AS
SELECT item_id, max(level)::INTEGER AS llc
FROM explosion
GROUP BY item_id;
