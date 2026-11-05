import { Alert, Box, Chip, Grid, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/apiClient";
import { useChartColors } from "../theme";
import { fmtChange, fmtDate, fmtMoney, fmtNumber, fmtPct } from "../utils/format";
import { ChartLegend, ChartTooltipBox } from "./ChartParts";
import { tickDate, useAxisProps } from "../utils/chart";
import { LabelValue } from "./Common";
import { QueryView } from "./StateViews";

/** Predictions made earlier (backtest or past production runs) next to what actually sold. */
export default function ForecastComparison({ sku }: { sku: string }) {
  const c = useChartColors();
  const { axis, grid } = useAxisProps();
  const [runId, setRunId] = useState<string | undefined>();
  const query = useQuery({ queryKey: ["comparison", sku, runId], queryFn: () => api.productComparison(sku, runId) });

  return (
    <QueryView query={query} errorTitle="No earlier forecasts to compare yet">
      {(d) => {
        const run = d.runs.find((r) => r.run_id === d.selected_run_id) ?? d.runs[0];
        const m = run.metrics;
        const data = d.points.map((p) => ({ ...p, band: p.lower !== null && p.upper !== null ? [p.lower, p.upper] : undefined }));
        return (
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ alignItems: { sm: "center" } }}>
              <TextField select size="small" label="Forecast made on" value={d.selected_run_id}
                         onChange={(e) => setRunId(e.target.value)} sx={{ minWidth: 280 }}>
                {d.runs.map((r) => (
                  <MenuItem key={r.run_id} value={r.run_id}>
                    {fmtDate(r.cutoff_date)} · {r.run_type === "backtest" ? "backtest" : "production"} · {r.model_name}
                  </MenuItem>
                ))}
              </TextField>
              <Chip size="small" variant="outlined"
                    label={run.run_type === "backtest"
                      ? "Backtest: model trained only on data up to this date"
                      : "Production forecast, now compared with actuals"} />
            </Stack>
            <Grid container spacing={2}>
              <Grid size={{ xs: 6, md: 3 }}><LabelValue label="Demand error (WAPE)" value={fmtPct(m?.wape)}
                hint="Sum of absolute errors divided by actual units; lower is better" /></Grid>
              <Grid size={{ xs: 6, md: 3 }}><LabelValue label="Mean absolute error" value={`${fmtNumber(m?.mae, 1)} units/day`} /></Grid>
              <Grid size={{ xs: 6, md: 3 }}><LabelValue label="Bias" value={fmtChange(m?.bias)}
                hint="Positive = forecast was too high; negative = too low" /></Grid>
              <Grid size={{ xs: 6, md: 3 }}><LabelValue label="Price error (MAPE)" value={m?.price_n_obs ? fmtPct(m.price_mape, 2) : "No price forecast"} /></Grid>
            </Grid>
            <Box>
              <ChartLegend items={[
                { label: "Actual units", color: c.actual },
                { label: "Earlier forecast", color: c.forecast },
                { label: "80% interval", color: c.band, kind: "band" },
              ]} />
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid {...grid} />
                  <XAxis dataKey="date" {...axis} tickFormatter={tickDate} minTickGap={28} />
                  <YAxis {...axis} width={44} />
                  <Tooltip cursor={{ stroke: c.text2, strokeWidth: 1 }} content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const p = payload[0].payload as (typeof data)[number];
                    return <ChartTooltipBox title={fmtDate(String(label))} rows={[
                      { label: "Actual", value: p.actual === null ? "not yet observed" : `${fmtNumber(p.actual)} units`, color: c.actual },
                      { label: "Forecast", value: `${fmtNumber(p.forecast, 1)} units`, color: c.forecast },
                      ...(p.forecast_price !== null ? [{ label: "Forecast price", value: fmtMoney(p.forecast_price, true) },
                        { label: "Actual price", value: p.actual_price === null ? "—" : fmtMoney(p.actual_price, true) }] : []),
                    ]} />;
                  }} />
                  <Area dataKey="band" stroke="none" fill={c.band} fillOpacity={0.16} isAnimationActive={false} activeDot={false} />
                  <Line dataKey="actual" stroke={c.actual} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
                  <Line dataKey="forecast" stroke={c.forecast} strokeWidth={2} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </Box>
            {run.days_with_actuals < run.horizon_days && (
              <Alert severity="info" variant="outlined">
                {run.days_with_actuals} of {run.horizon_days} forecast days have actual sales so far; the rest are not yet observed.
              </Alert>
            )}
            <Typography variant="caption" color="text.secondary">
              Forecast generated {fmtDate(run.generated_at)} for {fmtDate(d.points[0]?.date)} – {fmtDate(d.points[d.points.length - 1]?.date)}.
            </Typography>
          </Stack>
        );
      }}
    </QueryView>
  );
}
