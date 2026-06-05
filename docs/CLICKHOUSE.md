# ClickHouse audit log

## Run ClickHouse server
```bash
docker run -d --name clickhouse -p 8123:8123 -p 9000:9000 \
  -v ch-data:/var/lib/clickhouse \
  clickhouse/clickhouse-server:24.8
```

## Env config
```bash
CLICKHOUSE_URL=clickhouse://default:@localhost:9000/default
CLICKHOUSE_TABLE=audit_logs
```

## Schema
Auto-created on first write. Manual DDL in `audit_clickhouse._DDL`:

```sql
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID,
  tenant_id Nullable(UUID),
  actor_user_id Nullable(UUID),
  action LowCardinality(String),
  resource_type Nullable(String),
  resource_id Nullable(String),
  ip Nullable(String),
  user_agent Nullable(String),
  status LowCardinality(String),
  payload String,                    -- JSON serialized
  ts DateTime64(3, 'UTC')
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(ts)
ORDER BY (tenant_id, ts, id)
TTL ts + INTERVAL 365 DAY DELETE     -- 1-year retention; adjust per compliance need
```

## Migrate existing data
```bash
docker compose exec manager python -c "from backend import db_audit; print(db_audit.migrate_to_clickhouse())"
```

## Query examples
```sql
SELECT action, count() FROM audit_logs WHERE ts > now() - INTERVAL 1 DAY GROUP BY action ORDER BY 2 DESC;
SELECT * FROM audit_logs WHERE tenant_id = '...' ORDER BY ts DESC LIMIT 100;
```

## Deployment topology

The current implementation does **synchronous fire-and-forget** writes inside
the audit middleware: every mutation incurs one extra ClickHouse `INSERT`. This
is fine for low-to-moderate throughput (< 100 req/s) but is **not** the
recommended production setup at scale, because:

1. ClickHouse prefers large batched inserts (1k+ rows) — single-row inserts
   waste write amplification and merge churn.
2. Network latency to ClickHouse is now on the request hot path.

For production at scale, prefer one of:

* **Redis / Kafka buffer** — middleware pushes to a queue; a worker drains
  batches into ClickHouse every N seconds or M events.
* **Vector / Fluent Bit** — log audit rows to stdout/file, ship via a
  collector that batches into ClickHouse.

The dual-write contract (Postgres remains source of truth; ClickHouse is the
analytics replica) is unchanged regardless of transport.
