import Inventory2OutlinedIcon from "@mui/icons-material/Inventory2Outlined";
import {
  Box, Button, Grid, LinearProgress, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField,
  ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/apiClient";
import type { Dashboard } from "../api/types";
import { ChartTooltipBox } from "../components/ChartParts";
import { tickDate, tickMonth, useAxisProps } from "../utils/chart";
import { KpiCard, PageHeader, PriorityChip, Section, StockChip } from "../components/Common";
import { MultiSelect } from "../components/Filters";
import { EmptyState, LoadingBlock, QueryView } from "../components/StateViews";
import { categoryColor, useChartColors } from "../theme";
import { addDays, fmtCompact, fmtDate, fmtMoney, fmtMoneyCompact, fmtNumber } from "../utils/format";

const PRESETS = [
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 180, label: "6 months" },
  { days: 365, label: "12 months" },
];

export default function DashboardPage() {
  const [preset, setPreset] = useState<number | "custom">(30);
  const [custom, setCustom] = useState<{ start?: string; end?: string }>({});
  const [category, setCategory] = useState<string[]>([]);
  const [brand, setBrand] = useState<string[]>([]);
  const filters = useQuery({ queryKey: ["filters"], queryFn: api.productFilters });
  const status = useQuery({ queryKey: ["pipeline-status"], queryFn: api.pipelineStatus });
  const dataEnd = status.data?.freshness.data_end ?? undefined;
  const range = preset === "custom" ? custom : dataEnd ? { start: addDays(dataEnd, -(preset - 1)), end: dataEnd } : {};
  const query = useQuery({
    queryKey: ["dashboard", range, category, brand],
    queryFn: () => api.dashboard({ ...range, category, brand }),
    placeholderData: keepPreviousData,
    enabled: preset === "custom" || !!dataEnd || status.isError,
  });

  return (
    <>
      <PageHeader title="Retail analytics"
        subtitle={query.data?.has_data ? `${fmtDate(query.data.period.start)} – ${fmtDate(query.data.period.end)}, compared with the previous ${query.data.period.days} days` : undefined} />
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 3, flexWrap: "wrap", rowGap: 1.5 }}>
        <ToggleButtonGroup size="small" exclusive value={preset} onChange={(_, v) => v !== null && setPreset(v)} aria-label="Date range">
          {PRESETS.map((p) => <ToggleButton key={p.days} value={p.days}>{p.label}</ToggleButton>)}
          <ToggleButton value="custom">Custom</ToggleButton>
        </ToggleButtonGroup>
        {preset === "custom" && (
          <Stack direction="row" spacing={1}>
            <TextField size="small" type="date" label="From" value={custom.start ?? ""} slotProps={{ inputLabel: { shrink: true } }}
                       onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value || undefined }))} />
            <TextField size="small" type="date" label="To" value={custom.end ?? ""} slotProps={{ inputLabel: { shrink: true } }}
                       onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value || undefined }))} />
          </Stack>
        )}
        <MultiSelect label="Categories" value={category} onChange={setCategory} options={filters.data?.categories.map((c) => c.value) ?? []} />
        <MultiSelect label="Brands" value={brand} onChange={setBrand} options={filters.data?.brands.map((b) => b.value) ?? []} />
      </Stack>
      {query.isFetching && query.data && <LinearProgress sx={{ mb: 1, borderRadius: 1 }} />}
      <QueryView query={query} loading={<LoadingBlock height={420} />}>
        {(d) => (d.has_data ? <DashboardBody d={d} allCategories={filters.data?.categories.map((c) => c.value) ?? []} />
          : <EmptyState title="No sales data yet" action={<Button component={RouterLink} to="/pipelines" variant="outlined">Open pipeline status</Button>}>{d.message}</EmptyState>)}
      </QueryView>
    </>
  );
}

function DashboardBody({ d, allCategories }: { d: Dashboard; allCategories: string[] }) {
  const c = useChartColors();
  const { axis, grid } = useAxisProps();
  const navigate = useNavigate();
  const k = d.kpis;
  const bucketLabel = { day: "Daily", week: "Weekly", month: "Monthly" }[d.trend.bucket];
  return (
    <Stack spacing={3}>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}>
          <KpiCard label="Total revenue" value={fmtMoney(k.revenue.value)} change={k.revenue.change} changeLabel="vs prior" />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}>
          <KpiCard label="Units sold" value={fmtNumber(k.units.value)} change={k.units.change} changeLabel="vs prior" />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}>
          <KpiCard label="Active products" value={fmtNumber(k.active_products.value)} hint={`${k.active_products.selling} sold in period`} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 2.4 }}>
          <KpiCard label="Low-stock SKUs" value={fmtNumber(k.low_stock_skus.value)} icon={<Inventory2OutlinedIcon fontSize="small" />}
                   hint={k.low_stock_skus.out_of_stock ? `${k.low_stock_skus.out_of_stock} out of stock · review reorders` : "Review reorders"} />
        </Grid>
        <Grid size={{ xs: 12, sm: 12, lg: 2.4 }}>
          <KpiCard label="Forecast demand, next 30 days"
                   value={k.forecast_demand_30d.available ? `${fmtNumber(k.forecast_demand_30d.value)} units` : "Not available"}
                   change={k.forecast_demand_30d.available ? k.forecast_demand_30d.change_vs_last_30d : null} goodWhenUp={null}
                   changeLabel="vs last 30 days"
                   hint={k.forecast_demand_30d.available ? undefined : "Run forecast training"} />
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Section title="Sales revenue trend" subtitle={`${bucketLabel} revenue`}>
            {d.trend.points.length ? (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={d.trend.points} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
                  <defs>
                    <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={c.actual} stopOpacity={0.25} />
                      <stop offset="100%" stopColor={c.actual} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid {...grid} />
                  <XAxis dataKey="period" {...axis} tickFormatter={d.trend.bucket === "month" ? tickMonth : tickDate} minTickGap={24} />
                  <YAxis {...axis} width={56} tickFormatter={(v) => fmtMoneyCompact(v)} />
                  <Tooltip cursor={{ stroke: c.text2 }} content={({ active, payload, label }) => active && payload?.length ? (
                    <ChartTooltipBox title={`${d.trend.bucket === "day" ? "" : d.trend.bucket === "week" ? "Week of " : ""}${fmtDate(String(label), d.trend.bucket === "month" ? { month: "long", year: "numeric" } : undefined)}`}
                      rows={[{ label: "Revenue", value: fmtMoney(payload[0].payload.revenue), color: c.actual },
                             { label: "Units", value: fmtNumber(payload[0].payload.units) }]} />) : null} />
                  <Area dataKey="revenue" stroke={c.actual} strokeWidth={2} fill="url(#rev)" isAnimationActive={false}
                        activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <EmptyState title="No sales in this period" />}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 4 }}>
          <Section title="Top-selling products" subtitle="Units sold in period">
            <Stack spacing={1.25}>
              {d.top_products.slice(0, 7).map((p) => {
                const max = d.top_products[0]?.units || 1;
                return (
                  <Box key={p.sku} component={RouterLink} to={`/products/${p.sku}`} sx={{ color: "inherit", textDecoration: "none", "&:hover .name": { textDecoration: "underline" } }}>
                    <Stack direction="row" sx={{ justifyContent: "space-between", gap: 1 }}>
                      <Typography className="name" variant="body2" noWrap sx={{ minWidth: 0 }}>{p.name}</Typography>
                      <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{fmtNumber(p.units)}</Typography>
                    </Stack>
                    <Box sx={{ mt: 0.5, height: 6, borderRadius: 3, bgcolor: "action.hover" }}>
                      <Box sx={{ width: `${(p.units / max) * 100}%`, height: "100%", borderRadius: 3, bgcolor: c.actual }} />
                    </Box>
                  </Box>
                );
              })}
            </Stack>
          </Section>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Section title="Revenue by category">
            <ResponsiveContainer width="100%" height={Math.max(200, d.categories.length * 44)}>
              <BarChart data={d.categories} layout="vertical" margin={{ top: 0, right: 48, bottom: 0, left: 8 }} barCategoryGap={8}>
                <CartesianGrid {...grid} horizontal={false} vertical />
                <XAxis type="number" {...axis} tickFormatter={(v) => fmtMoneyCompact(v)} />
                <YAxis type="category" dataKey="category" {...axis} width={88} />
                <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }} content={({ active, payload }) => active && payload?.length ? (
                  <ChartTooltipBox title={payload[0].payload.category} rows={[
                    { label: "Revenue", value: fmtMoney(payload[0].payload.revenue) },
                    { label: "Units", value: fmtNumber(payload[0].payload.units) },
                    { label: "Products", value: String(payload[0].payload.products) }]} />) : null} />
                <Bar dataKey="revenue" radius={[0, 4, 4, 0]} isAnimationActive={false}
                     label={{ position: "right", fill: c.text2, fontSize: 12, formatter: (v: unknown) => fmtMoneyCompact(Number(v)) }}>
                  {d.categories.map((row) => <Cell key={row.category} fill={categoryColor(allCategories, row.category, c)} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Section title="Low-stock alerts" subtitle="Most urgent first, from the latest reorder plan"
                   action={<Button size="small" component={RouterLink} to="/inventory">All reorders</Button>}>
            {d.low_stock.length ? (
              <Box sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead><TableRow>
                    <TableCell>Product</TableCell><TableCell>Status</TableCell><TableCell>Priority</TableCell>
                    <TableCell align="right">Stock</TableCell><TableCell align="right">30-day demand</TableCell>
                    <TableCell align="right">Suggested order</TableCell>
                  </TableRow></TableHead>
                  <TableBody>
                    {d.low_stock.map((p) => (
                      <TableRow key={p.sku} hover sx={{ cursor: "pointer" }} onClick={() => navigate(`/products/${p.sku}`)}>
                        <TableCell sx={{ maxWidth: 220 }}>
                          <Typography sx={{ fontWeight: 600 }} variant="body2" noWrap>{p.name}</Typography>
                          <Typography variant="caption" color="text.secondary">{p.sku}</Typography>
                        </TableCell>
                        <TableCell><StockChip status={p.stock_status} /></TableCell>
                        <TableCell><PriorityChip priority={p.reorder_priority} /></TableCell>
                        <TableCell align="right">{fmtNumber(p.available_quantity)}</TableCell>
                        <TableCell align="right">{fmtCompact(p.forecast_demand_30d)}</TableCell>
                        <TableCell align="right">{p.reorder_quantity ? fmtNumber(p.reorder_quantity) : "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            ) : <EmptyState title="No low-stock products">Every product is above its reorder point.</EmptyState>}
          </Section>
        </Grid>
      </Grid>
    </Stack>
  );
}
