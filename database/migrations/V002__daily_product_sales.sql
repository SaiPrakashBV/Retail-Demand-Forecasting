-- Analytics-ready daily facts per product, refreshed by the ETL after each load.
CREATE MATERIALIZED VIEW daily_product_sales AS
SELECT product_id,
       sale_date,
       SUM(quantity)::integer                               AS units,
       SUM(revenue)::numeric(14, 2)                         AS revenue,
       (SUM(revenue) / NULLIF(SUM(quantity), 0))::numeric(12, 2) AS avg_price,
       BOOL_OR(on_promo)                                    AS on_promo,
       COUNT(*)::integer                                    AS transactions
FROM sales_transactions
GROUP BY product_id, sale_date;

CREATE UNIQUE INDEX daily_product_sales_pk ON daily_product_sales (product_id, sale_date);
CREATE INDEX daily_product_sales_date_idx ON daily_product_sales (sale_date);
