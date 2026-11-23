-- CPU-first baseline for shared single-node TKG deployments.
-- Historic 0001 seeds the deployment singleton at 32; 0011 promotes it
-- to 64. Consequently ALTER COLUMN DEFAULT alone is NOT sufficient for a
-- fresh database bootstrapped by the full migrations chain.
--
-- New and existing deployments which still hold value 64 are moved to 8.
-- All other operator-tuned values are retained. Note: an explicitly selected
-- 64 cannot be distinguished from the historical default. Operators requiring
-- 64 should reapply it via /api/v1/admin/deployment after upgrading.
-- The runtime scheduler hot-loads only on startup / authenticated admin PUT;
-- do not change the DB behind a running application without restarting the
-- application or using that API. This migration is applied on app deployment.
-- Retain existing range 1..256 and job retry/lease semantics.
ALTER TABLE deployment_settings
    ALTER COLUMN worker_concurrency SET DEFAULT 8;
UPDATE deployment_settings
   SET worker_concurrency = 8
 WHERE worker_concurrency = 64;
