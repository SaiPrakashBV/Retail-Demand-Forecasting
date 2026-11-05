import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DownloadIcon from "@mui/icons-material/Download";
import {
  Alert, Box, Button, Card, CardContent, Chip, Grid, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow,
  Tabs, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, ApiError } from "../api/apiClient";
import type { ProductDetail, ProductForecast } from "../api/types";
import { ChartLegend, ChartTooltipBox } from "../components/ChartParts";
import { tickDate, useAxisProps } from "../utils/chart";
import { KpiCard, LabelValue, PriorityChip, Section, StockChip } from "../components/Common";
import DemandChart from "../components/DemandChart";
import ForecastComparison from "../components/ForecastComparison";
import PriceChart from "../components/PriceChart";
import { EmptyState, ErrorState, LoadingBlock, QueryView } from "../components/StateViews";
import { useChartColors } from "../theme";
import { addDays, downloadText, fmtDate, fmtDateTime, fmtMoney, fmtNumber, toCsv } from "../utils/format";

export default function ProductDetailsPage() {
  const { sku = "" } = useParams();
  const product = useQuery({ queryKey: ["product", sku], queryFn: () => api.product(sku) });
  const forecast = useQuery({ queryKey: ["forecast", sku], queryFn: () => api.productForecast(sku) });
  const [tab, setTab] = useState("demand");

  return (
    <>
      <Button component={RouterLink} to="/products" startIcon={<ArrowBackIcon />} size="small" sx={{ mb: 1 }}>Catalog</Button>
      <QueryView query={product} loading={<LoadingBlock height={160} />} errorTitle="Product not found">
        {(p) => (
          <>
            <Stack direction={{ xs: "column", md: "row" }} sx={{ justifyContent: "space-between", gap: 2, mb: 3 }}>
              <Box>
                <Typography variant="h4" component="h1">{p.name}</Typography>
                <Stack direction="row" spacing={1} sx={{ mt: 0.75, alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
                  <Typography variant="body2" color="text.secondary">{p.sku} · {p.category} · {p.brand}</Typography>
                  <StockChip status={p.stock_status} />
                  {!p.is_active && <Chip size="small" label="Inactive" />}
                </Stack>
              </Box>
              <Box sx={{ textAlign: { md: "right" } }}>
                <Typography variant="h4" sx={{ fontVariantNumeric: "tabular-nums" }}>{fmtMoney(p.current_price, true)}</Typography>
                <Typography variant="caption" color="text.secondary">Latest actual selling price</Typography>
              </Box>
            </Stack>
            <Headline p={p} forecast={forecast.data} forecastError={forecast.error} />
            <Card sx={{ mt: 3 }}>
              <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile sx={{ px: 1, borderBottom: 1, borderColor: "divider" }}>
                <Tab value="demand" label="Demand" />
                <Tab value="price" label="Price" />
                <Tab value="comparison" label="Forecast vs actual" />
                <Tab value="inventory" label="Inventory" />
                <Tab value="table" label="Daily forecast" />
              </Tabs>
              <CardContent sx={{ p: { xs: 2, md: 3 } }}>
                {tab === "demand" && <DemandTab p={p} forecast={forecast.data} forecastError={forecast.error} />}
                {tab === "price" && <PriceTab p={p} forecast={forecast.data} />}
                {tab === "comparison" && <ForecastComparison sku={p.sku} />}
                {tab === "inventory" && <InventoryTab sku={p.sku} />}
                {tab === "table" && <DailyTable p={p} forecast={forecast.data} error={forecast.error} />}
              </CardContent>
            </Card>
          </>
        )}
      </QueryView>
    </>
  );
}

function Headline({ p, forecast, forecastError }: { p: ProductDetail; forecast?: ProductForecast; forecastError: unknown }) {
  const s = forecast?.summary;
  const rec = p.reorder;
  return (
    <>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="30-day forecast price"
                   value={s?.price_forecast_available ? fmtMoney(s.forecast_price_end, true) : "Unavailable"}
                   change={s?.price_forecast_available ? s.forecast_price_change : null} goodWhenUp={null} changeLabel="projected"
                   hint={s && !s.price_forecast_available
                     ? (p.price_forecast.history_days === 0 ? "Source has no price history" : "Not enough price history")
                     : undefined} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="Forecasted demand, 30 days" value={s ? `${fmtNumber(s.total_demand)} units` : "—"}
                   hint={s ? `80% range ${fmtNumber(s.total_demand_lower)} – ${fmtNumber(s.total_demand_upper)}` : "No forecast"} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="Current stock" value={`${fmtNumber(p.available_quantity)} units`}
                   hint={p.incoming_quantity ? `+${fmtNumber(p.incoming_quantity)} incoming ${fmtDate(p.incoming_expected_date, { month: "short", day: "numeric" })}` : `${fmtNumber(p.days_of_cover, 1)} days of cover`} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="Suggested reorder" value={rec ? `${fmtNumber(rec.reorder_quantity)} units` : "—"}
                   hint={rec ? <PriorityChip priority={rec.priority} /> : "Available after forecasting"} />
        </Grid>
      </Grid>
      {forecast && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          Forecast generated {fmtDateTime(forecast.generated_at)} from data up to {fmtDate(forecast.run.cutoff_date)} ·
          demand model <b>{forecast.run.demand_model}</b> v{forecast.run.demand_model_version ?? "?"}
          {forecast.run.price_model && <> · price model <b>{forecast.run.price_model}</b> v{forecast.run.price_model_version ?? "?"}</>}
        </Typography>
      )}
      {forecastError instanceof ApiError && forecastError.isUnavailable && (
        <Alert severity="info" variant="outlined" sx={{ mt: 2 }}>{forecastError.message}</Alert>
      )}
    </>
  );
}

function DemandTab({ p, forecast, forecastError }: { p: ProductDetail; forecast?: ProductForecast; forecastError: unknown }) {
  const [days, setDays] = useState(120);
  const end = p.data_end_date ?? undefined;
  const sales = useQuery({
    queryKey: ["sales", p.sku, days, end],
    queryFn: () => api.productSales(p.sku, { start: end ? addDays(end, -(days - 1)) : undefined, end, granularity: "day" }),
  });
  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1 }}>
        <Typography variant="subtitle2">Daily units sold and 30-day demand forecast</Typography>
        <ToggleButtonGroup size="small" exclusive value={days} onChange={(_, v) => v && setDays(v)} aria-label="History window">
          <ToggleButton value={60}>60d</ToggleButton><ToggleButton value={120}>120d</ToggleButton>
          <ToggleButton value={365}>1y</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
      <QueryView query={sales} loading={<LoadingBlock height={340} />}>
        {(h) => h.points.length ? <DemandChart history={h.points} forecast={forecast?.points ?? null} />
          : <EmptyState title="No sales history in this window" />}
      </QueryView>
      {forecastError !== null && forecastError !== undefined && !(forecastError instanceof ApiError && forecastError.isUnavailable) && (
        <ErrorState error={forecastError} title="Forecast could not be loaded" />
      )}
    </Stack>
  );
}

function PriceTab({ p, forecast }: { p: ProductDetail; forecast?: ProductForecast }) {
  const end = p.data_end_date ?? undefined;
  const prices = useQuery({
    queryKey: ["prices", p.sku, end],
    queryFn: () => api.productPrices(p.sku, { start: end ? addDays(end, -119) : undefined, end }),
  });
  return (
    <Stack spacing={2}>
      <Typography variant="subtitle2">Historical vs forecasted selling price</Typography>
      <QueryView query={prices} loading={<LoadingBlock height={320} />}>
        {(h) => <PriceChart history={h} forecast={forecast?.points ?? null} />}
      </QueryView>
      <Typography variant="caption" color="text.secondary">
        Forecast prices are estimates of the expected selling price (including likely promotions). They never change catalog prices.
      </Typography>
    </Stack>
  );
}

function InventoryTab({ sku }: { sku: string }) {
  const c = useChartColors();
  const { axis, grid } = useAxisProps();
  const inv = useQuery({ queryKey: ["inventory", sku], queryFn: () => api.productInventory(sku, 120) });
  return (
    <QueryView query={inv}>
      {(d) => {
        const r = d.recommendation;
        return (
          <Stack spacing={3}>
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 4 }}>
                <Section title="Inventory recommendation">
                  {r ? (
                    <Stack spacing={1.5}>
                      <Stack direction="row" spacing={3}>
                        <LabelValue label="Current stock" value={`${fmtNumber(r.available_quantity)} units`} />
                        <LabelValue label="Suggested reorder" value={`${fmtNumber(r.reorder_quantity)} units`} />
                      </Stack>
                      <PriorityChip priority={r.priority} />
                      <Typography variant="body2">{r.explanation}</Typography>
                    </Stack>
                  ) : <Typography variant="body2" color="text.secondary">Recommendations are calculated after each forecast run.</Typography>}
                </Section>
              </Grid>
              <Grid size={{ xs: 12, md: 8 }}>
                <Section title="How the suggestion is calculated" subtitle="Reorder point = demand over the lead time + safety stock">
                  {r ? (
                    <Grid container spacing={2}>
                      {[
                        ["Inventory position", fmtNumber(r.inventory_position), "Available − reserved + incoming − backordered"],
                        ["Reorder point", fmtNumber(r.reorder_point), undefined],
                        ["Lead-time demand", `${fmtNumber(r.lead_time_demand)} over ${r.lead_time_days} days`, undefined],
                        ["Safety stock", fmtNumber(r.safety_stock), "Covers forecast error at the target service level"],
                        ["Target stock", fmtNumber(r.target_stock), `Demand over lead time + ${r.review_period_days}-day review period + safety stock`],
                        ["Predicted stock-out", r.predicted_stockout_date ? fmtDate(r.predicted_stockout_date) : "Not within 30 days", undefined],
                        ["Reserved / backordered", `${fmtNumber(r.reserved_quantity)} / ${fmtNumber(r.backordered_quantity)}`, undefined],
                        ["Incoming", r.incoming_quantity ? `${fmtNumber(r.incoming_quantity)} on ${fmtDate(d.incoming_expected_date)}` : "None", undefined],
                        ["Order rules", `MOQ ${d.min_order_qty} · packs of ${d.pack_size}`, undefined],
                      ].map(([label, value, hint]) => (
                        <Grid key={label} size={{ xs: 6, sm: 4 }}><LabelValue label={label as string} value={value} hint={hint as string | undefined} /></Grid>
                      ))}
                    </Grid>
                  ) : <Typography variant="body2" color="text.secondary">No recommendation yet.</Typography>}
                </Section>
              </Grid>
            </Grid>
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>End-of-day stock, last 120 days</Typography>
              {d.snapshots.length ? (
                <>
                  <ChartLegend items={[
                    { label: "Stock on hand", color: c.actual },
                    ...(r ? [{ label: "Reorder point", color: c.forecast, kind: "dashed" as const },
                             { label: "Safety stock", color: c.baseline, kind: "dashed" as const }] : []),
                  ]} />
                  <ResponsiveContainer width="100%" height={260}>
                    <ComposedChart data={d.snapshots} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                      <CartesianGrid {...grid} />
                      <XAxis dataKey="date" {...axis} tickFormatter={tickDate} minTickGap={28} />
                      <YAxis {...axis} width={48} />
                      <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                        <ChartTooltipBox title={fmtDate(String(label))} rows={[{ label: "On hand", value: `${fmtNumber(payload[0].payload.quantity)} units`, color: c.actual }]}
                          note={payload[0].payload.quantity === 0 ? "Out of stock" : undefined} />) : null} />
                      <Area dataKey="quantity" type="stepAfter" stroke={c.actual} strokeWidth={2} fill={c.actual} fillOpacity={0.1} isAnimationActive={false} />
                      {r && <ReferenceLine y={Number(r.reorder_point)} stroke={c.forecast} strokeDasharray="5 4" />}
                      {r && <ReferenceLine y={Number(r.safety_stock)} stroke={c.baseline} strokeDasharray="5 4" />}
                      <Line dataKey="quantity" stroke="none" dot={false} legendType="none" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </>
              ) : <EmptyState title="No inventory snapshots loaded" />}
            </Box>
          </Stack>
        );
      }}
    </QueryView>
  );
}

function DailyTable({ p, forecast, error }: { p: ProductDetail; forecast?: ProductForecast; error: unknown }) {
  if (!forecast) return error ? <ErrorState error={error} /> : <LoadingBlock lines={6} />;
  const rows = forecast.points.map((f) => ({
    date: f.date, forecast_units: f.demand, lower_units: f.demand_lower, upper_units: f.demand_upper,
    forecast_price: f.price, price_lower: f.price_lower, price_upper: f.price_upper,
    price_status: f.price_status, actual_units: f.actual_units, actual_price: f.actual_price,
  }));
  return (
    <Stack spacing={2}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
        <Typography variant="subtitle2">One prediction per day for the next {rows.length} days</Typography>
        <Button size="small" variant="outlined" startIcon={<DownloadIcon />}
                onClick={() => downloadText(`${p.sku}_forecast_${forecast.run.cutoff_date}.csv`, toCsv(rows))}>CSV</Button>
      </Stack>
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead><TableRow>
            <TableCell>Date</TableCell><TableCell align="right">Actual price</TableCell><TableCell align="right">Forecast price</TableCell>
            <TableCell align="right">Forecast demand</TableCell><TableCell align="right">80% range</TableCell>
            <TableCell align="right">Actual units</TableCell>
          </TableRow></TableHead>
          <TableBody>
            {forecast.points.map((f) => (
              <TableRow key={f.date}>
                <TableCell>{fmtDate(f.date, { weekday: "short", month: "short", day: "numeric" })}</TableCell>
                <TableCell align="right">{f.actual_price !== null ? fmtMoney(f.actual_price, true) : <Typography variant="caption" color="text.secondary">Not yet observed</Typography>}</TableCell>
                <TableCell align="right">{f.price_status === "forecast" ? fmtMoney(f.price, true) : <Typography variant="caption" color="text.secondary">Unavailable</Typography>}</TableCell>
                <TableCell align="right">{fmtNumber(f.demand, 1)} units</TableCell>
                <TableCell align="right">{f.demand_lower !== null ? `${fmtNumber(f.demand_lower, 1)} – ${fmtNumber(f.demand_upper, 1)}` : "—"}</TableCell>
                <TableCell align="right">{f.actual_units !== null ? fmtNumber(f.actual_units) : <Typography variant="caption" color="text.secondary">Not yet observed</Typography>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Stack>
  );
}
