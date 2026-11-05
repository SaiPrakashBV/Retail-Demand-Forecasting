import ModelTrainingIcon from "@mui/icons-material/ModelTraining";
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid, LinearProgress, Stack, Table,
  TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, ApiError } from "../api/apiClient";
import type { BacktestModelRow, TrainingJob } from "../api/types";
import { ChartLegend, ChartTooltipBox } from "../components/ChartParts";
import { tickDate, useAxisProps } from "../utils/chart";
import { KpiCard, PageHeader, RunStatusChip, Section } from "../components/Common";
import { MultiSelect } from "../components/Filters";
import { EmptyState, ErrorState, LoadingBlock, QueryView } from "../components/StateViews";
import { useChartColors } from "../theme";
import { fmtChange, fmtDate, fmtDateTime, fmtMoney, fmtNumber, fmtPct, titleCase } from "../utils/format";

const MODEL_LABEL: Record<string, string> = {
  xgboost: "XGBoost (global)", prophet: "Prophet (per product)", seasonal_naive: "Seasonal naive (baseline)",
  xgboost_price: "XGBoost price model", naive_last_regular: "Last regular price (naive)",
};
const label = (m: string) => MODEL_LABEL[m] ?? titleCase(m);

function readKey(): string {
  try { return sessionStorage.getItem("train-api-key") ?? ""; } catch { return ""; }
}

export default function ForecastPage() {
  const [category, setCategory] = useState<string[]>([]);
  const [dialog, setDialog] = useState(false);
  const qc = useQueryClient();
  const filters = useQuery({ queryKey: ["filters"], queryFn: api.productFilters });
  const accuracy = useQuery({ queryKey: ["accuracy", category], queryFn: () => api.accuracy({ category }) });
  const portfolio = useQuery({ queryKey: ["portfolio", category], queryFn: () => api.portfolio(category) });
  const jobs = useQuery({
    queryKey: ["jobs"], queryFn: api.jobs,
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running") ? 3000 : false),
  });
  const active = jobs.data?.find((j) => j.status === "queued" || j.status === "running");
  const latest = jobs.data?.[0];

  // When a job we saw running finishes, refresh everything that depends on forecasts.
  const watching = useRef<string | null>(null);
  useEffect(() => {
    if (active) watching.current = active.job_id;
    else if (watching.current && latest?.job_id === watching.current) {
      watching.current = null;
      if (latest.status === "succeeded") qc.invalidateQueries();
    }
  }, [active, latest, qc]);

  return (
    <>
      <PageHeader title="Forecasts"
        subtitle={accuracy.data ? `Latest run ${fmtDateTime(accuracy.data.run.generated_at)} · data up to ${fmtDate(accuracy.data.run.cutoff_date)}` : "Demand and price forecasting"}
        actions={<>
          <MultiSelect label="Categories" value={category} onChange={setCategory} options={filters.data?.categories.map((c) => c.value) ?? []} />
          <Button variant="contained" startIcon={<ModelTrainingIcon />} onClick={() => setDialog(true)} disabled={!!active}>
            {active ? "Training…" : "Train models"}
          </Button>
        </>} />
      {active && <JobProgress job={active} />}
      {!active && latest?.status === "failed" && (
        <Alert severity="error" variant="outlined" sx={{ mb: 2 }}>
          The last training job failed ({fmtDateTime(latest.finished_at)}): {latest.error}
        </Alert>
      )}
      <TrainDialog open={dialog} onClose={() => setDialog(false)} />

      <QueryView query={accuracy} loading={<LoadingBlock height={360} />}
                 errorTitle="No forecasts yet">
        {(acc) => {
          const demand = acc.backtest.demand;
          const sel = demand.find((d) => d.is_selected);
          const naive = demand.find((d) => d.model_name === "seasonal_naive");
          const priceSel = acc.backtest.price.find((d) => d.is_selected);
          return (
            <Stack spacing={3}>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6, lg: 3 }}><KpiCard label="Demand model in use" value={label(acc.run.demand_model)}
                  hint={`v${acc.run.demand_model_version ?? "?"} · ${acc.run.products_forecast ?? "—"} products`} /></Grid>
                <Grid size={{ xs: 12, sm: 6, lg: 3 }}><KpiCard label="Demand error (WAPE)" value={fmtPct(sel?.wape)}
                  hint={naive?.wape && sel?.wape ? `${fmtPct(1 - sel.wape / naive.wape, 0)} lower than the naive baseline` : undefined} /></Grid>
                <Grid size={{ xs: 12, sm: 6, lg: 3 }}><KpiCard label="Price model in use" value={acc.run.price_model ? label(acc.run.price_model) : "None"}
                  hint={acc.run.price_model_version ? `v${acc.run.price_model_version}` : "No product has enough price history"} /></Grid>
                <Grid size={{ xs: 12, sm: 6, lg: 3 }}><KpiCard label="Price error (MAPE)" value={fmtPct(priceSel?.mape, 2)}
                  hint={priceSel ? `${priceSel.products} products with price history` : undefined} /></Grid>
              </Grid>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, lg: 6 }}>
                  <ModelComparison title="Demand models: backtest error" rows={demand} metric="wape" unit="WAPE"
                    subtitle="Same rolling 30-day windows for every model, scored on in-stock days. The lowest error is used." />
                </Grid>
                <Grid size={{ xs: 12, lg: 6 }}>
                  <ModelComparison title="Price models: backtest error" rows={acc.backtest.price} metric="mape" unit="MAPE"
                    subtitle="Mean absolute % error of the daily selling price." />
                </Grid>
              </Grid>
              <PortfolioChart query={portfolio} />
              <Section title="Earlier forecasts vs actual sales" subtitle="Each backtest run only saw data up to its cutoff date">
                {acc.forecast_vs_actual.length ? (
                  <Box sx={{ overflowX: "auto" }}>
                    <Table size="small">
                      <TableHead><TableRow>
                        <TableCell>Forecast made on</TableCell><TableCell>Type</TableCell><TableCell>Demand model</TableCell>
                        <TableCell align="right">Products</TableCell><TableCell align="right">Actual units</TableCell>
                        <TableCell align="right">Forecast units</TableCell><TableCell align="right">WAPE</TableCell>
                        <TableCell align="right">Bias</TableCell><TableCell align="right">Price MAPE</TableCell>
                      </TableRow></TableHead>
                      <TableBody>
                        {acc.forecast_vs_actual.map((r) => (
                          <TableRow key={r.run_id}>
                            <TableCell>{fmtDate(r.cutoff_date)}</TableCell>
                            <TableCell><Chip size="small" variant="outlined" label={r.run_type} /></TableCell>
                            <TableCell>{label(r.demand_model)}</TableCell>
                            <TableCell align="right">{fmtNumber(r.metrics?.products)}</TableCell>
                            <TableCell align="right">{fmtNumber(r.metrics?.actual_units)}</TableCell>
                            <TableCell align="right">{fmtNumber(r.metrics?.forecast_units)}</TableCell>
                            <TableCell align="right">{fmtPct(r.metrics?.wape)}</TableCell>
                            <TableCell align="right">{fmtChange(r.metrics?.bias)}</TableCell>
                            <TableCell align="right">{r.metrics?.price_n_obs ? fmtPct(r.metrics.price_mape, 2) : "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </Box>
                ) : <EmptyState title="No forecasts have actuals yet" />}
              </Section>
              {acc.products && <ProductAccuracy rows={acc.products.demand} />}
            </Stack>
          );
        }}
      </QueryView>

      <Box sx={{ mt: 3 }}>
        <Section title="Training jobs" subtitle="Started from this page or by the Airflow forecast_training workflow">
          <QueryView query={jobs} loading={<LoadingBlock lines={3} />}>
            {(list) => list.length ? (
              <Box sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead><TableRow><TableCell>Requested</TableCell><TableCell>By</TableCell><TableCell>Status</TableCell>
                    <TableCell>Duration</TableCell><TableCell>Result</TableCell></TableRow></TableHead>
                  <TableBody>
                    {list.slice(0, 8).map((j) => (
                      <TableRow key={j.job_id}>
                        <TableCell>{fmtDateTime(j.requested_at)}</TableCell>
                        <TableCell>{j.requested_by}</TableCell>
                        <TableCell><RunStatusChip status={j.status} /></TableCell>
                        <TableCell>{j.started_at && j.finished_at ? `${Math.round((+new Date(j.finished_at) - +new Date(j.started_at)) / 1000)} s` : "—"}</TableCell>
                        <TableCell sx={{ maxWidth: 520 }}><Typography variant="body2" color={j.error ? "error" : "text.secondary"}>{j.error ?? j.message}</Typography></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            ) : <EmptyState title="No training jobs yet" />}
          </QueryView>
        </Section>
      </Box>
    </>
  );
}

function JobProgress({ job }: { job: TrainingJob }) {
  return (
    <Alert severity="info" variant="outlined" sx={{ mb: 2, "& .MuiAlert-message": { width: "100%" } }} icon={<ModelTrainingIcon />}>
      <Stack spacing={1}>
        <Typography sx={{ fontWeight: 600 }} variant="body2">
          Training {job.status === "queued" ? "is queued; waiting for the forecast worker" : `in progress: ${job.message ?? job.stage}`}
        </Typography>
        <LinearProgress variant={job.status === "queued" ? "indeterminate" : "determinate"} value={job.progress} />
        <Typography variant="caption" color="text.secondary">{job.progress}% · started {fmtDateTime(job.started_at ?? job.requested_at)}</Typography>
      </Stack>
    </Alert>
  );
}

function TrainDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [key, setKey] = useState(readKey);
  const qc = useQueryClient();
  const train = useMutation({
    mutationFn: () => api.train(key, { requested_by: "ui", reason: "started from the Forecasts page" }),
    onSuccess: () => {
      try { sessionStorage.setItem("train-api-key", key); } catch { /* storage unavailable */ }
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onClose();
    },
  });
  const conflict = train.error instanceof ApiError && train.error.status === 409;
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Train forecasting models</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Starts a background job: backtests XGBoost and Prophet for demand and the price models, keeps the most accurate,
          and publishes new 30-day forecasts and reorder suggestions. It usually takes 1–3 minutes.
        </Typography>
        <TextField fullWidth size="small" type="password" label="Training API key" value={key} autoFocus
                   onChange={(e) => setKey(e.target.value)} helperText="TRAIN_API_KEY configured on the API" />
        {train.error && !conflict && <Box sx={{ mt: 2 }}><ErrorState error={train.error} title="Could not start training" /></Box>}
        {conflict && <Alert severity="info" sx={{ mt: 2 }}>A training job is already running; its progress is shown on this page.</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => train.mutate()} disabled={!key || train.isPending}>Start training</Button>
      </DialogActions>
    </Dialog>
  );
}

function ModelComparison({ title, subtitle, rows, metric, unit }: {
  title: string; subtitle: string; rows: BacktestModelRow[]; metric: "wape" | "mape"; unit: string;
}) {
  const c = useChartColors();
  const { axis, grid } = useAxisProps();
  if (!rows.length) return <Section title={title}><EmptyState title="Not available">No products have enough history for this model.</EmptyState></Section>;
  const data = [...rows].sort((a, b) => (a[metric] ?? 1) - (b[metric] ?? 1)).map((r) => ({ ...r, name: label(r.model_name), value: r[metric] ?? 0 }));
  return (
    <Section title={title} subtitle={subtitle}>
      <ResponsiveContainer width="100%" height={data.length * 52 + 20}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 60, left: 8, bottom: 0 }} barCategoryGap={10}>
          <CartesianGrid {...grid} horizontal={false} vertical />
          <XAxis type="number" {...axis} tickFormatter={(v) => fmtPct(v, 0)} domain={[0, "auto"]} />
          <YAxis type="category" dataKey="name" {...axis} width={170} />
          <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }} content={({ active, payload }) => active && payload?.length ? (
            <ChartTooltipBox title={payload[0].payload.name} rows={[
              { label: unit, value: fmtPct(payload[0].payload.value, 2) },
              { label: "MAE", value: fmtNumber(payload[0].payload.mae, 2) },
              { label: "Bias", value: fmtChange(payload[0].payload.bias) },
              { label: "Products", value: String(payload[0].payload.products) }]}
              note={payload[0].payload.is_selected ? "Used for this run's forecasts" : undefined} />) : null} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}
               label={{ position: "right", fill: c.text2, fontSize: 12, formatter: (v: unknown) => fmtPct(Number(v), metric === "mape" ? 2 : 1) }}>
            {data.map((d) => <Cell key={d.model_name} fill={d.is_selected ? c.actual : c.baseline} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <ChartLegend items={[{ label: "Selected for this run", color: c.actual, kind: "bar" }, { label: "Other candidates", color: c.baseline, kind: "bar" }]} />
    </Section>
  );
}

function PortfolioChart({ query }: { query: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.portfolio>>>> }) {
  const c = useChartColors();
  const { axis, grid } = useAxisProps();
  return (
    <Section title="Total forecast demand, next 30 days" subtitle="Sum over products in the selected categories">
      <QueryView query={query} loading={<LoadingBlock height={280} />}>
        {(p) => {
          const data = p.daily.map((d) => ({ ...d, band: d.demand_lower !== null && d.demand_upper !== null ? [d.demand_lower, d.demand_upper] : undefined }));
          return (
            <>
              <Stack direction="row" spacing={4} sx={{ mb: 1 }}>
                <Typography variant="body2">Units: <b>{fmtNumber(p.total_demand)}</b></Typography>
                <Typography variant="body2">Revenue at forecast prices: <b>{fmtMoney(p.total_revenue)}</b></Typography>
              </Stack>
              <ChartLegend items={[{ label: "Forecast units", color: c.forecast }, { label: "80% interval (sum of product bands)", color: c.band, kind: "band" }]} />
              <ResponsiveContainer width="100%" height={280}>
                <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid {...grid} />
                  <XAxis dataKey="date" {...axis} tickFormatter={tickDate} minTickGap={24} />
                  <YAxis {...axis} width={52} tickFormatter={(v) => fmtNumber(v)} />
                  <Tooltip content={({ active, payload, label: l }) => active && payload?.length ? (
                    <ChartTooltipBox title={fmtDate(String(l), { weekday: "short", month: "short", day: "numeric" })} rows={[
                      { label: "Forecast", value: `${fmtNumber(payload[0].payload.demand)} units`, color: c.forecast },
                      { label: "Revenue", value: fmtMoney(payload[0].payload.revenue) }]} />) : null} />
                  <Area dataKey="band" stroke="none" fill={c.band} fillOpacity={0.16} isAnimationActive={false} activeDot={false} />
                  <Line dataKey="demand" stroke={c.forecast} strokeWidth={2} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </>
          );
        }}
      </QueryView>
    </Section>
  );
}

function ProductAccuracy({ rows }: { rows: { sku: string; name: string; category: string; model_name: string; wape: number | null; mae: number | null; bias: number | null; n_obs: number }[] }) {
  const [showAll, setShowAll] = useState(false);
  const list = showAll ? rows : rows.slice(0, 10);
  return (
    <Section title="Demand accuracy by product" subtitle="Backtest error of the model in use, best first"
             action={rows.length > 10 && <Button size="small" onClick={() => setShowAll((s) => !s)}>{showAll ? "Show fewer" : `Show all ${rows.length}`}</Button>}>
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead><TableRow><TableCell>Product</TableCell><TableCell>Category</TableCell>
            <TableCell align="right">WAPE</TableCell><TableCell align="right">MAE (units/day)</TableCell>
            <TableCell align="right">Bias</TableCell><TableCell align="right">Days scored</TableCell></TableRow></TableHead>
          <TableBody>
            {list.map((r) => (
              <TableRow key={r.sku} hover>
                <TableCell><Typography component={RouterLink} to={`/products/${r.sku}`} variant="body2"
                                       sx={{ fontWeight: 600, color: "inherit" }}>{r.name}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>{r.sku}</Typography></TableCell>
                <TableCell>{r.category}</TableCell>
                <TableCell align="right">{fmtPct(r.wape)}</TableCell>
                <TableCell align="right">{fmtNumber(r.mae, 1)}</TableCell>
                <TableCell align="right">{fmtChange(r.bias)}</TableCell>
                <TableCell align="right">{r.n_obs}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
    </Section>
  );
}
