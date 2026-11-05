-- Products predicted to run out before stock can arrive count as low stock, even when an
-- incoming order means no new order is suggested.
CREATE OR REPLACE VIEW product_overview AS
WITH data_end AS (
    SELECT COALESCE(MAX(sale_date), CURRENT_DATE) AS d FROM daily_product_sales
),
recent AS (
    SELECT s.product_id, SUM(s.units) AS units_30d, SUM(s.revenue) AS revenue_30d
    FROM daily_product_sales s, data_end
    WHERE s.sale_date > data_end.d - 30
    GROUP BY s.product_id
),
fc AS (
    SELECT f.product_id,
           SUM(f.demand_prediction)                               AS forecast_demand_30d,
           SUM(f.demand_prediction * COALESCE(f.price_prediction, p.current_price)) AS forecast_revenue_30d,
           BOOL_OR(f.price_status = 'forecast')                   AS price_forecast_available,
           (ARRAY_AGG(f.price_prediction ORDER BY f.forecast_date DESC))[1] AS forecast_price_end,
           AVG(f.price_prediction)                                AS forecast_price_avg,
           MIN(f.generated_at)                                    AS forecast_generated_at
    FROM forecasts f
    JOIN latest_production_run r ON r.run_id = f.run_id
    JOIN products p ON p.product_id = f.product_id
    GROUP BY f.product_id
),
rec AS (
    SELECT rr.*
    FROM reorder_recommendations rr
    JOIN latest_production_run r ON r.run_id = rr.run_id
)
SELECT p.product_id, p.sku, p.name, p.category, p.brand, p.current_price, p.unit_cost,
       p.supplier_lead_time_days, p.min_order_qty, p.pack_size, p.launch_date, p.is_active,
       COALESCE(i.available_quantity, 0)                              AS available_quantity,
       COALESCE(i.reserved_quantity, 0)                               AS reserved_quantity,
       COALESCE(i.incoming_quantity, 0)                               AS incoming_quantity,
       i.incoming_expected_date,
       COALESCE(i.backordered_quantity, 0)                            AS backordered_quantity,
       i.updated_at                                                   AS inventory_updated_at,
       COALESCE(recent.units_30d, 0)                                  AS units_30d,
       COALESCE(recent.revenue_30d, 0)                                AS revenue_30d,
       fc.forecast_demand_30d, fc.forecast_revenue_30d, fc.forecast_price_end, fc.forecast_price_avg,
       COALESCE(fc.price_forecast_available, FALSE)                   AS price_forecast_available,
       fc.forecast_generated_at,
       rec.reorder_quantity, rec.reorder_point, rec.safety_stock, rec.priority AS reorder_priority,
       rec.predicted_stockout_date, rec.days_of_cover,
       CASE
           WHEN COALESCE(i.available_quantity, 0) - COALESCE(i.reserved_quantity, 0) <= 0 THEN 'out_of_stock'
           WHEN rec.reorder_quantity > 0 OR rec.priority = 'critical' THEN 'low_stock'
           -- no recommendation yet: fall back to less than two weeks of recent average sales
           WHEN rec.product_id IS NULL
                AND COALESCE(i.available_quantity, 0) - COALESCE(i.reserved_quantity, 0)
                    < COALESCE(recent.units_30d, 0) / 30.0 * 14 THEN 'low_stock'
           ELSE 'in_stock'
       END                                                            AS stock_status
FROM products p
LEFT JOIN inventory i ON i.product_id = p.product_id
LEFT JOIN recent ON recent.product_id = p.product_id
LEFT JOIN fc ON fc.product_id = p.product_id
LEFT JOIN rec ON rec.product_id = p.product_id;
