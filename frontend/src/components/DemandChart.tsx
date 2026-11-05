import { Box } from "@mui/material";
import { useMemo } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ForecastPoint, SalesPoint } from "../api/types";
import { useChartColors } from "../theme";
import { fmtDate, fmtNumber } from "../utils/format";
import { ChartLegend, ChartTooltipBox, type TooltipRow } from "./ChartParts";
import { tickDate, useAxisProps } from "../utils/chart";

interface Row {
  date: string;
  actual?: number;
  forecast?: number;
  band?: [number, number];
  promo?: number;
  stockout?: number;
}

/** Actual daily units (with promo and stock-out markers) followed by the 30-day forecast and its 80% band. */
export default function DemandChart({ history, forecast, height = 340 }: {
  history: SalesPoint[]; forecast: ForecastPoint[] | null; height?: number;
}) {
  const c = useChartColors();
  const { axis, grid } = useAxisProps();
  const data = useMemo<Row[]>(() => {
    const rows: Row[] = history.map((h) => ({
      date: h.date, actual: h.units,
      promo: h.on_promo ? h.units : undefined,
      stockout: h.in_stock === false ? h.units : undefined,
    }));
    if (forecast?.length) {
      const last = rows[rows.length - 1];
      if (last) { last.forecast = last.actual; last.band = [last.actual ?? 0, last.actual ?? 0]; }
      for (const f of forecast) {
        rows.push({ date: f.date, forecast: f.demand,
                    band: f.demand_lower !== null && f.demand_upper !== null ? [f.demand_lower, f.demand_upper] : undefined });
      }
    }
    return rows;
  }, [history, forecast]);
  const start = forecast?.[0]?.date;
  const hasPromo = history.some((h) => h.on_promo);
  const hasStockout = history.some((h) => h.in_stock === false);

  return (
    <Box>
      <ChartLegend items={[
        { label: "Actual units", color: c.actual },
        ...(forecast?.length ? [{ label: "Forecast", color: c.forecast }, { label: "80% interval", color: c.band, kind: "band" as const }] : []),
        ...(hasPromo ? [{ label: "Promotion day", color: c.actual, kind: "diamond" as const }] : []),
        ...(hasStockout ? [{ label: "Stock-out day (sales capped)", color: c.status.critical, kind: "dot" as const }] : []),
      ]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid {...grid} />
          <XAxis dataKey="date" {...axis} tickFormatter={tickDate} minTickGap={28} />
          <YAxis {...axis} width={44} tickFormatter={(v) => fmtNumber(v)} />
          <Tooltip cursor={{ stroke: c.text2, strokeWidth: 1 }} content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const r = payload[0].payload as Row;
            const rows: TooltipRow[] = [];
            if (r.actual !== undefined) rows.push({ label: "Actual", value: `${fmtNumber(r.actual)} units`, color: c.actual });
            if (r.forecast !== undefined && r.actual === undefined) {
              rows.push({ label: "Forecast", value: `${fmtNumber(r.forecast, 1)} units`, color: c.forecast });
              if (r.band) rows.push({ label: "80% interval", value: `${fmtNumber(r.band[0], 1)} – ${fmtNumber(r.band[1], 1)}` });
            }
            const note = [r.promo !== undefined && "Promotion", r.stockout !== undefined && "Stock-out: sales capped by stock"]
              .filter(Boolean).join(" · ");
            return <ChartTooltipBox title={fmtDate(String(label), { weekday: "short", month: "short", day: "numeric", year: "numeric" })}
                                    rows={rows} note={note || undefined} />;
          }} />
          <Area dataKey="band" stroke="none" fill={c.band} fillOpacity={0.18} isAnimationActive={false} activeDot={false} />
          <Line dataKey="actual" stroke={c.actual} strokeWidth={2} dot={false} isAnimationActive={false}
                activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} />
          <Line dataKey="forecast" stroke={c.forecast} strokeWidth={2} dot={false} isAnimationActive={false}
                activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} />
          {hasPromo && <Scatter dataKey="promo" fill={c.actual} shape="diamond" isAnimationActive={false} legendType="none" />}
          {hasStockout && <Scatter dataKey="stockout" fill={c.status.critical} isAnimationActive={false} legendType="none" />}
          {start && <ReferenceLine x={start} stroke={c.text2} strokeDasharray="4 4"
                                   label={{ value: "Forecast", position: "insideTopLeft", fill: c.text2, fontSize: 12 }} />}
        </ComposedChart>
      </ResponsiveContainer>
    </Box>
  );
}
