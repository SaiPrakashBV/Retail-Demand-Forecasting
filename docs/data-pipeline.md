# Data pipeline

## Sources

**OData** (`ODATA_BASE_URL`, default the bundled `mock-odata` service). The entity sets read are:

| Entity set | Key | Extraction |
|---|---|---|
| `Products` | Sku | full every run |
| `SalesTransactions` | TransactionId | incremental on `SaleDate` |
| `PriceHistory` | Sku + PriceDate | incremental on `PriceDate` |
| `Inventory` | Sku | full every run (current position) |
| `InventorySnapshots` | Sku + SnapshotDate | incremental on `SnapshotDate` |

Incremental reads use `$filter=<date> ge '<watermark − ETL_OVERLAP_DAYS>'`, so late corrections
are picked up. Every `@odata.nextLink` page is followed, and requests are retried with backoff.
To point at a real service, set `ODATA_BASE_URL`. If its property names differ, adapt the
`COLUMNS` mapping in `airflow/tasks/clean_data.py`.

**CSV drop-zone** (`data/incoming/`). Optional `products.csv`, `sales.csv`, `prices.csv` and
`inventory.csv` are ingested by the next run and moved to `data/incoming/processed/<run>/`. Their
columns are shown in `data/sample/`. When a CSV and OData supply the same key, the CSV row wins,
since it is treated as a manual correction.

> On Linux hosts, Airflow runs as uid 50000, so make the folder writable for it:
> `chmod 777 data/incoming` (or `sudo chown 50000 data/incoming`).

## Steps (`retail_etl`, daily at 01:00 UTC)

1. **start**: records a `data_pipeline_runs` row (`running`).
2. **extract**: writes raw JSON per entity to the run's work folder (the `etl-data` volume).
3. **clean**: standardises names and types, trims text, upper-cases SKUs and drops exact
   duplicates. Values that cannot be parsed become empty, and the original record is kept.
4. **validate**: applies the data-quality rules below. Each invalid record goes to
   `quarantine_records` with a reason and its original values. If more than
   `ETL_MAX_INVALID_RATIO` (default 5%) of any entity is invalid, or a full catalog load has no
   valid products, the task fails *without retries* and nothing is loaded.
5. **transform**: shapes rows for each table, and applies CSV-over-OData priority.
6. **load**: one transaction of `INSERT … ON CONFLICT DO UPDATE` upserts, so re-running a day is
   safe. It then advances the watermarks and refreshes the `daily_product_sales` view.
7. **update_status**: marks the run `succeeded` with extracted, loaded and quarantined counts.
8. **trigger_forecast_training**: starts the `forecast_training` DAG.

A failure at any step marks the run `failed` with the error message (task failure callback).
Runs, counts, freshness and quarantined samples are shown on the **Pipeline status** page.

## Data-quality rules

| Entity | Rule |
|---|---|
| products | valid SKU format; name, category and price > 0 present; integer lead time ≥ 0, MOQ ≥ 1, pack ≥ 1; no duplicate SKU in batch |
| sales | transaction id present; valid and known SKU; valid date, not in the future; integer quantity ≥ 0; price > 0; conflicting duplicate ids quarantined (first kept) |
| prices | known SKU; valid date; price > 0; type `regular`/`promo`; one price per SKU and day |
| inventory | known SKU; non-negative integer quantities; one row per SKU |
| snapshots | known SKU; valid date; non-negative integer quantity |

The mock source deliberately injects about 0.5% bad records (negative quantities, missing or
unknown SKUs, conflicting duplicate ids, zero prices, impossible dates), so these rules are
exercised on every run.

## Run locally without Airflow

```bash
cd airflow && RETAIL_DATABASE_URL=postgresql+psycopg2://retail:retail@localhost:5432/retail \
  ODATA_BASE_URL=http://localhost:8081/odata ETL_WORK_DIR=/tmp/etl CSV_INCOMING_DIR=../data/incoming \
  PYTHONPATH=.. python -m tasks.pipeline
```
