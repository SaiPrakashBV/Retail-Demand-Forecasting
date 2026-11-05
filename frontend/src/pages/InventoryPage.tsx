import DownloadIcon from "@mui/icons-material/Download";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import SearchIcon from "@mui/icons-material/Search";
import {
  Box, Button, Card, Chip, Collapse, FormControlLabel, Grid, IconButton, InputAdornment, LinearProgress, MenuItem,
  Pagination, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api } from "../api/apiClient";
import type { Priority, ReorderItem } from "../api/types";
import { KpiCard, PageHeader, PriorityChip } from "../components/Common";
import { MultiSelect } from "../components/Filters";
import { EmptyState, LoadingBlock, QueryView } from "../components/StateViews";
import { fmtDate, fmtMoney, fmtNumber } from "../utils/format";

const PRIORITIES: Priority[] = ["critical", "high", "medium", "low"];
const PAGE = 50;

export default function InventoryPage() {
  const [priority, setPriority] = useState<string[]>([]);
  const [category, setCategory] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [actionable, setActionable] = useState(true);
  const [sort, setSort] = useState("priority");
  const [page, setPage] = useState(1);
  const filters = useQuery({ queryKey: ["filters"], queryFn: api.productFilters });
  const query = useQuery({
    queryKey: ["reorders", priority, category, q, actionable, sort, page],
    queryFn: () => api.reorders({ priority, category, q: q || undefined, actionable_only: actionable, sort, page, page_size: PAGE }),
    placeholderData: keepPreviousData,
  });
  const counts = query.data?.priority_counts ?? {};
  const exportUrl = api.reportDownloadUrl("reorder-recommendations", "xlsx", { category });

  return (
    <>
      <PageHeader title="Inventory and reorders"
        subtitle="Order suggestions from the latest forecast: expected demand over each supplier's lead time plus safety stock"
        actions={<Button variant="outlined" startIcon={<DownloadIcon />} href={exportUrl}>Export to Excel</Button>} />
      <Grid container spacing={2} sx={{ mb: 2 }}>
        {PRIORITIES.slice(0, 3).map((p) => (
          <Grid key={p} size={{ xs: 12, sm: 4 }}>
            <KpiCard label={{ critical: "Critical: will run out before stock can arrive", high: "High: at or below reorder point",
                              medium: "Medium: reorder point within a week" }[p as "critical" | "high" | "medium"]}
                     value={fmtNumber(counts[p] ?? 0)} hint={<PriorityChip priority={p} />} />
          </Grid>
        ))}
      </Grid>
      <Card sx={{ mb: 2, p: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ alignItems: { md: "center" }, flexWrap: "wrap", rowGap: 1.5 }}>
          <TextField size="small" placeholder="Search name or SKU" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }}
                     slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }} />
          <MultiSelect label="Priority" value={priority} onChange={(v) => { setPriority(v); setPage(1); }} options={PRIORITIES} minWidth={150} />
          <MultiSelect label="Category" value={category} onChange={(v) => { setCategory(v); setPage(1); }}
                       options={filters.data?.categories.map((c) => c.value) ?? []} />
          <TextField select size="small" label="Sort by" value={sort} onChange={(e) => setSort(e.target.value)} sx={{ minWidth: 180 }}>
            <MenuItem value="priority">Urgency</MenuItem><MenuItem value="stockout_date">Stock-out date</MenuItem>
            <MenuItem value="reorder_quantity">Order quantity</MenuItem><MenuItem value="days_of_cover">Days of cover</MenuItem>
          </TextField>
          <FormControlLabel control={<Switch checked={actionable} onChange={(e) => { setActionable(e.target.checked); setPage(1); }} />}
                            label="Needs action only" />
        </Stack>
      </Card>
      {query.isFetching && query.data && <LinearProgress sx={{ mb: 1 }} />}
      <QueryView query={query} loading={<LoadingBlock lines={8} />} errorTitle="Reorder plan not available">
        {(d) => d.items.length ? (
          <>
            <Card sx={{ overflowX: "auto" }}>
              <Table size="small">
                <TableHead><TableRow>
                  <TableCell padding="checkbox" /><TableCell>Product</TableCell><TableCell>Priority</TableCell>
                  <TableCell align="right">Available</TableCell><TableCell align="right">Incoming</TableCell>
                  <TableCell align="right">Position</TableCell><TableCell align="right">Reorder point</TableCell>
                  <TableCell align="right">Days of cover</TableCell><TableCell>Predicted stock-out</TableCell>
                  <TableCell align="right">Suggested order</TableCell><TableCell align="right">Order value</TableCell>
                </TableRow></TableHead>
                <TableBody>{d.items.map((r) => <ReorderRow key={r.sku} r={r} />)}</TableBody>
              </Table>
            </Card>
            {d.total > PAGE && <Stack sx={{ mt: 2, alignItems: "center" }}>
              <Pagination count={Math.ceil(d.total / PAGE)} page={page} onChange={(_, p) => setPage(p)} /></Stack>}
          </>
        ) : (
          <EmptyState title={actionable ? "No products need reordering" : "No products match"}>
            {actionable ? "Every product is above its reorder point. Turn off “Needs action only” to see all stock levels." : "Change the filters."}
          </EmptyState>
        )}
      </QueryView>
    </>
  );
}

function ReorderRow({ r }: { r: ReorderItem }) {
  const [open, setOpen] = useState(false);
  return (
    <Fragment>
      <TableRow hover>
        <TableCell padding="checkbox">
          <IconButton size="small" onClick={() => setOpen((o) => !o)} aria-label={open ? "Hide explanation" : "Show explanation"}>
            {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
          </IconButton>
        </TableCell>
        <TableCell sx={{ maxWidth: 240 }}>
          <Typography component={RouterLink} to={`/products/${r.sku}`} variant="body2" noWrap sx={{ fontWeight: 600, color: "inherit", display: "block" }}>{r.name}</Typography>
          <Typography variant="caption" color="text.secondary">{r.sku} · {r.category}</Typography>
        </TableCell>
        <TableCell><PriorityChip priority={r.priority} /></TableCell>
        <TableCell align="right">{fmtNumber(r.available_quantity)}</TableCell>
        <TableCell align="right">{r.incoming_quantity ? fmtNumber(r.incoming_quantity) : "—"}</TableCell>
        <TableCell align="right">{fmtNumber(r.inventory_position)}</TableCell>
        <TableCell align="right">{fmtNumber(r.reorder_point)}</TableCell>
        <TableCell align="right">{fmtNumber(r.days_of_cover, 1)}</TableCell>
        <TableCell>{r.predicted_stockout_date ? fmtDate(r.predicted_stockout_date) : "Not within 30 days"}</TableCell>
        <TableCell align="right">
          {r.reorder_quantity ? <Typography sx={{ fontWeight: 700 }} variant="body2">{fmtNumber(r.reorder_quantity)}</Typography>
            : <Chip size="small" variant="outlined" label="Expedite incoming" />}
        </TableCell>
        <TableCell align="right">{r.order_value ? fmtMoney(r.order_value) : "—"}</TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={11} sx={{ py: 0, borderBottom: open ? undefined : "none" }}>
          <Collapse in={open} unmountOnExit>
            <Box sx={{ py: 1.5, px: 1 }}>
              <Typography variant="body2">{r.explanation}</Typography>
              <Typography variant="caption" color="text.secondary">
                Lead time {r.lead_time_days} days · lead-time demand {fmtNumber(r.lead_time_demand)} · safety stock {fmtNumber(r.safety_stock)} ·
                target {fmtNumber(r.target_stock)} · MOQ {r.min_order_qty} · pack {r.pack_size}
              </Typography>
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </Fragment>
  );
}
