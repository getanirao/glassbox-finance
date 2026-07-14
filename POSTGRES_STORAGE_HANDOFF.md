# Future Handoff: Neon/Postgres News Cache Storage

This repo is now role-ready (`--bot`, `--engine`, `--news-worker`, `--news-worker-once`), but cache persistence is still local file based under `data/.news_cache.json`.

Use this handoff to make multiple machines and GitHub Actions workers share one durable news cache.

## Goal

Move news cache source-of-truth from local JSON to Postgres/Neon while preserving local JSON as a fallback/export snapshot.

The target architecture:

- Oracle VPS runs `python main.py --bot` or Docker Compose default service.
- GitHub Actions and optional laptops run `python main.py --news-worker-once` or `--news-worker`.
- All workers dedupe into the same Postgres tables.
- Only the Oracle engine/bot sends Discord dashboards and final recommendations.

## Environment Variables

Add these to `.env.example` when implementation begins:

```env
DATABASE_URL=postgresql://...
STORAGE_BACKEND=postgres
NODE_ID=oracle-main
NEWS_WORKER_BATCH_SIZE=10
NEWS_LEASE_MINUTES=10
```

GitHub Actions already exposes `DATABASE_URL: ${{ secrets.DATABASE_URL }}` for future use.

## Proposed Schema

```sql
create table if not exists news_headlines (
  id bigserial primary key,
  ticker text not null,
  headline text not null,
  headline_hash text not null unique,
  source text,
  url text,
  published_at timestamptz,
  fetched_at timestamptz not null default now(),
  net_score double precision not null,
  pos_score double precision not null,
  neg_score double precision not null,
  critical_neg double precision not null default 0,
  scorer_version text not null,
  fetched_by text not null
);

create index if not exists idx_news_headlines_ticker_time
  on news_headlines (ticker, fetched_at desc);

create table if not exists worker_leases (
  ticker text primary key,
  leased_by text not null,
  lease_until timestamptz not null,
  updated_at timestamptz not null default now()
);
```

## Code Touchpoints

Add a small `storage.py` module instead of spreading DB calls through the engine.

Suggested API:

```python
def load_news_cache():
    ...

def save_news_entries(entries):
    ...

def claim_tickers(node_id, limit, lease_minutes):
    ...

def release_tickers(node_id, tickers):
    ...
```

Then update:

- `engine.load_news_cache()`
- `engine.save_news_cache()`
- `engine.run_news_worker()`
- `engine.run_news_stream()`

Keep the existing JSON format as an adapter output:

```python
{"headlines": [ ... ]}
```

That lets `compute_rolling_sentiment()` stay unchanged initially.

## Deduping Rule

Use a normalized hash:

```python
headline_hash = sha256(f"{ticker}|{normalized_title}".encode()).hexdigest()
```

Normalize by lowercasing, collapsing whitespace, and stripping punctuation that does not affect meaning.

Insert with:

```sql
insert into news_headlines (...)
values (...)
on conflict (headline_hash) do nothing;
```

## Worker Lease Rule

Each news worker should claim a small batch:

```sql
insert into worker_leases (ticker, leased_by, lease_until)
values ($1, $2, now() + interval '10 minutes')
on conflict (ticker) do update
set leased_by = excluded.leased_by,
    lease_until = excluded.lease_until,
    updated_at = now()
where worker_leases.lease_until < now();
```

Only fetch tickers whose lease was acquired by this worker.

## Acceptance Checks

- Two simultaneous `--news-worker-once` processes do not insert duplicate headlines.
- Oracle engine can restart and load cache from Postgres with no local JSON present.
- GitHub Actions worker writes rows when `DATABASE_URL` secret is present.
- If Postgres is unavailable, engine falls back to local JSON and logs the degraded mode.
- Discord dashboard is still sent only by the bot/engine service, never by news workers.
