# User guide

Open http://localhost:3000. The search box at the top finds products by name, SKU, brand or
category from any page. Press Enter to see every match in the catalog.

## Dashboard
Revenue, units sold, active products, low-stock SKUs and forecast demand for the next 30 days.
Each figure is compared with the previous period of the same length. Use the date presets or a
custom range, and the category and brand filters. The low-stock list is ordered by urgency; click
a row to open the product.

## Products
Search and filter by category, brand, price range, stock status and minimum 30-day forecast, and
sort by name, price, stock, forecast demand, recent revenue or days of cover. Switch between cards
and a table. The URL keeps your filters, so a search can be bookmarked or shared.

## Product details
- **Demand:** daily units sold, with promotion days and stock-out days (when sales were capped by
  stock) marked, followed by the 30-day forecast and its 80% range.
- **Price:** historical selling price and the forecast price with its range. When the price
  can't be forecast, the page says why.
- **Forecast vs actual:** pick an earlier forecast and compare it with what actually sold, with
  its error (WAPE), mean error, bias and price error.
- **Inventory:** the suggested order, how it was calculated, and the stock history against the
  reorder point and safety stock.
- **Daily forecast:** one row per day for 30 days, downloadable as CSV. Days without an actual yet
  say "Not yet observed".

The line under the headline figures shows when the forecast was made and which model versions
were used.

## Forecasts
Which demand and price models are in use and how accurate they were in the backtest, compared with
the other candidates and the naive baseline. Also shows total forecast demand, earlier forecasts
against actual sales, and accuracy by product. **Train models** starts a background training job
and needs the training API key (`TRAIN_API_KEY`). Its progress appears on the page, and every page
refreshes when it finishes.

## Inventory
Products that need an order, or will run out before stock could arrive. Each row shows stock,
incoming quantity, inventory position, reorder point, days of cover, predicted stock-out date,
suggested quantity and order value. Expand a row to read the explanation. "Expedite incoming"
means an order is already on the way but arrives too late.

## Reports
Sales trends, product prices, forecast vs actual, inventory levels, stock-out risk and reorder
recommendations. Filter by dates, category and SKU or name; sort by any column; download as CSV or
Excel.

## Pipeline status
How recent the data is, recent ingestion runs with counts (click a quarantine count to see the
rejected records and why), training jobs, and links to Airflow and MLflow.
