import { Box, Paper, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { useChartColors } from "../theme";

export interface TooltipRow {
  label: string;
  value: string;
  color?: string;
  dashed?: boolean;
}

/** Themed tooltip; rows are built by each chart so units and labels are explicit. */
export function ChartTooltipBox({ title, rows, note }: { title: string; rows: TooltipRow[]; note?: ReactNode }) {
  const c = useChartColors();
  return (
    <Paper variant="outlined" sx={{ px: 1.5, py: 1, minWidth: 170, boxShadow: 3 }}>
      <Typography variant="caption" sx={{ fontWeight: 700, color: c.text }}>{title}</Typography>
      <Stack spacing={0.25} sx={{ mt: 0.5 }}>
        {rows.map((r) => (
          <Stack key={r.label} direction="row" spacing={1.5} sx={{ justifyContent: "space-between", alignItems: "center" }}>
            <Stack direction="row" spacing={0.75} sx={{ alignItems: "center" }}>
              {r.color && <Box sx={{ width: 10, height: 2, bgcolor: r.dashed ? "transparent" : r.color,
                                     borderTop: r.dashed ? `2px dashed ${r.color}` : undefined }} />}
              <Typography variant="caption" sx={{ color: c.text2 }}>{r.label}</Typography>
            </Stack>
            <Typography variant="caption" sx={{ fontWeight: 600, color: c.text, fontVariantNumeric: "tabular-nums" }}>{r.value}</Typography>
          </Stack>
        ))}
      </Stack>
      {note && <Typography variant="caption" sx={{ display: "block", mt: 0.5, color: c.text2 }}>{note}</Typography>}
    </Paper>
  );
}

export interface LegendItem {
  label: string;
  color: string;
  kind?: "line" | "dashed" | "band" | "dot" | "diamond" | "bar";
}

/** Legend shown above every multi-series chart (identity is never colour-only: labels + mark shapes). */
export function ChartLegend({ items }: { items: LegendItem[] }) {
  const c = useChartColors();
  return (
    <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 0.5, mb: 1 }} role="list" aria-label="Chart legend">
      {items.map((i) => (
        <Stack key={i.label} direction="row" spacing={0.75} sx={{ alignItems: "center" }} role="listitem">
          <LegendMark color={i.color} kind={i.kind ?? "line"} />
          <Typography variant="caption" sx={{ color: c.text2 }}>{i.label}</Typography>
        </Stack>
      ))}
    </Stack>
  );
}

function LegendMark({ color, kind }: { color: string; kind: NonNullable<LegendItem["kind"]> }) {
  if (kind === "band") return <Box sx={{ width: 16, height: 10, bgcolor: color, opacity: 0.22, borderRadius: 0.5 }} />;
  if (kind === "dot") return <Box sx={{ width: 8, height: 8, bgcolor: color, borderRadius: "50%" }} />;
  if (kind === "diamond") return <Box sx={{ width: 8, height: 8, bgcolor: color, transform: "rotate(45deg)" }} />;
  if (kind === "bar") return <Box sx={{ width: 10, height: 10, bgcolor: color, borderRadius: 0.5 }} />;
  return <Box sx={{ width: 16, height: 0, borderTop: `2px ${kind === "dashed" ? "dashed" : "solid"} ${color}` }} />;
}
