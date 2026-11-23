-- CPU-first baseline for NEW deployments. The previous 64-worker default was
-- designed for larger general-purpose model concurrency and database pools.
-- A shared CPU-only inference service (one active inference, four waiters)
-- and a small application DB pool benefit from a lower initial outer cap.
--
-- Do NOT UPDATE deployment_settings rows: these represent operator-owned
-- runtime choices and must not change unexpectedly on migration.
-- Existing Server 55 must be tuned explicitly through /admin/deployment.
-- Worker bounds (1..256), retry budgets, source leases and checkpoints remain.
ALTER TABLE deployment_settings
    ALTER COLUMN worker_concurrency SET DEFAULT 8;
