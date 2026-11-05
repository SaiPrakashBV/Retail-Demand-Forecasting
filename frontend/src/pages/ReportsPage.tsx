import DownloadIcon from "@mui/icons-material/Download";
import {
  Box, Button, Card, CardActionArea, CardContent, Grid, LinearProgress, MenuItem, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TableSortLabel, TextField, Typography,
} from "@mui/material";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/apiClient";
import { PageHeader, Section } from "../components/Common";
import { MultiSelect } from "../components/Filters";
import { EmptyState, LoadingBlock, QueryView } from "../components/StateViews";
import { fmtNumber, titleCase } from "../utils/format";

const DATED = new Set(["sales-trends", "product-prices", "forecast-vs-actual"]);
const DESCRIPTIONS: Record<string, string> = {
  "sales-trends": "Units, revenue and average price per product per day.",
  "product-prices": "Recorded selling prices (regular and promotional).",
  "forecast-vs-actual": "Every earlier forecast next to the actual units and price that followed.",
  "inventory-levels": "Stock, incoming orders, cover and status for every product.",
  "stockout-risk": "Products predicted to run out, with dates and explanations.",
  "reorder-recommendations": "Suggested purchase orders with quantities and values.",
};

function cell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? fmtNumber(v) : v.toFixed(2);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  const s = String(v);
  return /^\d{4}-\d{2}-\d{2}T/.test(s) ? s.slice(0, 16).replace("T", " ") : s;
}

export default function ReportsPage() {
  const reports = useQuery({ queryKey: ["reports"], queryFn: api.reports });
  const filters = useQuery({ queryKey: ["filters"], queryFn: api.productFilters });
  const [report, setReport] = useState("sales-trends");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [category, setCategory] = useState<string[]>([]);
  const [sku, setSku] = useState("");
  const [sort, setSort] = useState<string | undefined>();
  const [descending, setDescending] = useState(true);
  const params = { start: DATED.has(report) ? start || undefined : undefined, end: DATED.has(report) ? end || undefined : undefined,
                   category, sku: sku || undefined, sort, descending };
  const preview = useQuery({
    queryKey: ["report", report, params], queryFn: () => api.reportPreview(report, { ...params, limit: 100 }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader title="Reports" subtitle="Preview the first 100 rows, then download the full report as CSV or Excel" />
      <Grid container spacing={2} sx={{ mb: 2 }}>
        {(reports.data ?? []).map((r) => (
          <Grid key={r.id} size={{ xs: 12, sm: 6, lg: 4 }}>
            <Card sx={{ height: "100%", borderColor: r.id === report ? "primary.main" : undefined, borderWidth: r.id === report ? 2 : 1 }}>
              <CardActionArea onClick={() => { setReport(r.id); setSort(undefined); }} sx={{ height: "100%" }}>
                <CardContent>
                  <Typography sx={{ fontWeight: 700 }} variant="subtitle1">{titleCase(r.id)}</Typography>
                  <Typography variant="body2" color="text.secondary">{DESCRIPTIONS[r.id] ?? r.title}</Typography>
                </CardContent>
              </CardActionArea>
            </Card>
          </Grid>
        ))}
      </Grid>
      <Section title={titleCase(report)} subtitle={preview.data ? `${fmtNumber(preview.data.total_rows)} rows` : undefined}
        action={
          <Stack direction="row" spacing={1}>
            <Button size="small" variant="outlined" startIcon={<DownloadIcon />} href={api.reportDownloadUrl(report, "csv", params)}>CSV</Button>
            <Button size="small" variant="contained" startIcon={<DownloadIcon />} href={api.reportDownloadUrl(report, "xlsx", params)}>Excel</Button>
          </Stack>
        }>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 2, flexWrap: "wrap", rowGap: 1.5 }}>
          {DATED.has(report) && <>
            <TextField size="small" type="date" label="From" value={start} onChange={(e) => setStart(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
            <TextField size="small" type="date" label="To" value={end} onChange={(e) => setEnd(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
          </>}
          <MultiSelect label="Category" value={category} onChange={setCategory} options={filters.data?.categories.map((c) => c.value) ?? []} />
          <TextField size="small" label="SKU or name" value={sku} onChange={(e) => setSku(e.target.value)} />
          {preview.data && (
            <TextField select size="small" label="Sort by" value={sort ?? ""} sx={{ minWidth: 180 }} onChange={(e) => setSort(e.target.value || undefined)}>
              <MenuItem value="">Default order</MenuItem>
              {preview.data.columns.map((c) => <MenuItem key={c} value={c}>{titleCase(c)}</MenuItem>)}
            </TextField>
          )}
        </Stack>
        {preview.isFetching && preview.data && <LinearProgress sx={{ mb: 1 }} />}
        <QueryView query={preview} loading={<LoadingBlock lines={8} />}>
          {(d) => d.rows.length ? (
            <Box sx={{ overflowX: "auto", maxHeight: 560 }}>
              <Table size="small" stickyHeader>
                <TableHead><TableRow>
                  {d.columns.map((c) => (
                    <TableCell key={c} sortDirection={sort === c ? (descending ? "desc" : "asc") : false} sx={{ whiteSpace: "nowrap" }}>
                      <TableSortLabel active={sort === c} direction={sort === c && !descending ? "asc" : "desc"}
                                      onClick={() => { if (sort === c) setDescending((x) => !x); else { setSort(c); setDescending(true); } }}>
                        {titleCase(c)}
                      </TableSortLabel>
                    </TableCell>
                  ))}
                </TableRow></TableHead>
                <TableBody>
                  {d.rows.map((r, i) => (
                    <TableRow key={i} hover>
                      {d.columns.map((c) => <TableCell key={c} sx={{ whiteSpace: c === "explanation" ? "normal" : "nowrap", minWidth: c === "explanation" ? 320 : undefined }}>{cell(r[c])}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          ) : <EmptyState title="No rows for these filters" />}
        </QueryView>
      </Section>
    </>
  );
}
