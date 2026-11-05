import { Alert, Box } from "@mui/material";
import { useMemo } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { ForecastPoint, PriceHistory } from "../api/types";
import { useChartColors } from "../theme";
import { fmtDate, fmtMoney } from "../utils/format";
import { ChartLegend, ChartTooltipBox, type TooltipRow } from "./ChartParts";
import { tickDate, useAxisProps } from "../utils/chart";
import { EmptyState } from "./StateViews";

interface Row {
  date: string;
  actual?: number;
  promo?: number;
  forecast?: number;
  band?: [number, number];
}

/** Historical selling price (promo days marked) and, when available, the forecast price with its band. */
export default function PriceChart({ history, forecast, height = 320 }: {
  history: PriceHistory; forecast: ForecastPoint[] | null; height?: number;
}) {
  const c = useChartColors();
  const { axis, grid } = useAxisProps();
  const priced = (forecast ?? []).filter((f) => f.price_status === "forecast" && f.price !== null);
  const data = useMemo<Row[]>(() => {
    const rows: Row[] = history.points.map((p) => ({
      date: p.date, actual: p.actual_price, promo: p.price_type === "promo" ? p.actual_price : undefined,
    }));
    if (priced.length) {
      const last = rows[rows.length - 1];
      if (last?.actual !== undefined) { last.forecast = last.actual; last.band = [last.actual, last.actual]; }
      for (const f of priced) {
        rows.push({ date: f.date, forecast: f.price as number,
                    band: f.price_lower !== null && f.price_upper !== null ? [f.price_lower, f.price_upper] : undefined });
      }
    }
    return rows;
  }, [history, priced]);

  if (!history.has_history) {
    return (
      <EmptyState title="No price history for this product">
        {history.forecast.reason} The latest known catalog price is {fmtMoney(history.current_price, true)}.
      </EmptyState>
    );
  }
  const values = data.flatMap((d) => [d.actual, d.forecast, ...(d.band ?? [])]).filter((v): v is number => v !== undefined);
  const lo = Math.min(...values), hi = Math.max(...values);
  const pad = Math.max((hi - lo) * 0.15, hi * 0.02);

  return (
    <Box>
      {!priced.length && (
        <Alert severity="info" variant="outlined" sx={{ mb: 2 }}>
          Future prices are unavailable: {history.forecast.reason}
        </Alert>
      )}
      <ChartLegend items={[
        { label: "Actual selling price", color: c.actual },
        { label: "Promotion price", color: c.actual, kind: "diamond" },
        ...(priced.length ? [{ label: "Forecast price (estimate)", color: c.forecast }, { label: "80% interval", color: c.band, kind: "band" as const }] : []),
      ]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
          <CartesianGrid {...grid} />
          <XAxis dataKey="date" {...axis} tickFormatter={tickDate} minTickGap={28} />
          <YAxis {...axis} width={56} domain={[Math.max(0, lo - pad), hi + pad]} tickFormatter={(v) => fmtMoney(v, v < 100)} />
          <Tooltip cursor={{ stroke: c.text2, strokeWidth: 1 }} content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const r = payload[0].payload as Row;
            const rows: TooltipRow[] = [];
            if (r.actual !== undefined) rows.push({ label: r.promo !== undefined ? "Actual (promo)" : "Actual", value: fmtMoney(r.actual, true), color: c.actual });
            if (r.forecast !== undefined && r.actual === undefined) {
              rows.push({ label: "Forecast", value: fmtMoney(r.forecast, true), color: c.forecast });
              if (r.band) rows.push({ label: "80% interval", value: `${fmtMoney(r.band[0], true)} – ${fmtMoney(r.band[1], true)}` });
            }
            return <ChartTooltipBox title={fmtDate(String(label))} rows={rows} />;
          }} />
          <Area dataKey="band" stroke="none" fill={c.band} fillOpacity={0.18} isAnimationActive={false} activeDot={false} />
          <Line dataKey="actual" type="stepAfter" stroke={c.actual} strokeWidth={2} dot={false} isAnimationActive={false}
                activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} />
          <Scatter dataKey="promo" fill={c.actual} shape="diamond" isAnimationActive={false} legendType="none" />
          <Line dataKey="forecast" stroke={c.forecast} strokeWidth={2} dot={false} isAnimationActive={false}
                activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} />
          {priced[0] && <ReferenceLine x={priced[0].date} stroke={c.text2} strokeDasharray="4 4"
                                       label={{ value: "Forecast", position: "insideTopLeft", fill: c.text2, fontSize: 12 }} />}
        </ComposedChart>
      </ResponsiveContainer>
    </Box>
  );
}
