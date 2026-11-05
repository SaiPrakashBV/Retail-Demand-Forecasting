import GridViewIcon from "@mui/icons-material/GridView";
import SearchIcon from "@mui/icons-material/Search";
import ViewListIcon from "@mui/icons-material/ViewList";
import {
  Box, Button, Card, CardActionArea, CardContent, Chip, Divider, Grid, InputAdornment, LinearProgress, MenuItem,
  Pagination, Slider, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, ToggleButton,
  ToggleButtonGroup, Typography,
} from "@mui/material";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/apiClient";
import type { ProductCard, StockStatus } from "../api/types";
import { ChangeBadge, PageHeader, StockChip } from "../components/Common";
import { MultiSelect } from "../components/Filters";
import { EmptyState, LoadingBlock, QueryView } from "../components/StateViews";
import { fmtMoney, fmtNumber } from "../utils/format";

const SORTS = [
  { value: "relevance", label: "Best match" },
  { value: "name", label: "Name" },
  { value: "price", label: "Price" },
  { value: "stock", label: "Stock" },
  { value: "forecast_demand", label: "Forecast demand" },
  { value: "revenue_30d", label: "Revenue, last 30 days" },
  { value: "days_of_cover", label: "Days of cover" },
];
const STATUSES: { value: StockStatus; label: string }[] = [
  { value: "in_stock", label: "In stock" }, { value: "low_stock", label: "Low stock" }, { value: "out_of_stock", label: "Out of stock" },
];

export default function ProductsPage() {
  const [params, setParams] = useSearchParams();
  const get = (k: string) => params.get(k) ?? undefined;
  const all = (k: string) => params.getAll(k);
  const q = get("q") ?? "";
  const [text, setText] = useState(q);
  const [syncedQ, setSyncedQ] = useState(q);
  if (q !== syncedQ) { // URL changed (e.g. global search): show it in the box
    setSyncedQ(q);
    setText(q);
  }
  const view = (get("view") as "cards" | "table") ?? "cards";
  const page = Number(get("page") ?? 1);
  const sort = get("sort") ?? (q ? "relevance" : "name");
  const order = (get("order") as "asc" | "desc") ?? (["forecast_demand", "revenue_30d"].includes(sort) ? "desc" : "asc");

  const update = (changes: Record<string, string | string[] | undefined>, resetPage = true) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v !== undefined && v !== "") next.set(k, v);
    }
    if (resetPage) next.delete("page");
    setParams(next, { replace: true });
  };

  const filters = useQuery({ queryKey: ["filters"], queryFn: api.productFilters });
  const maxPrice = Math.ceil(filters.data?.max_price ?? 500);
  const price: [number, number] = [Number(get("min_price") ?? 0), Number(get("max_price") ?? maxPrice)];
  const [priceDraft, setPriceDraft] = useState<[number, number] | null>(null);

  const query = useQuery({
    queryKey: ["products", params.toString()],
    queryFn: () => api.products({
      q: q || undefined, category: all("category"), brand: all("brand"), stock_status: all("stock_status"),
      min_price: get("min_price") ? Number(get("min_price")) : undefined,
      max_price: get("max_price") ? Number(get("max_price")) : undefined,
      min_forecast: get("min_forecast") ? Number(get("min_forecast")) : undefined,
      sort, order, page, page_size: view === "cards" ? 24 : 50,
    }),
    placeholderData: keepPreviousData,
  });
  const activeFilters = ["category", "brand", "stock_status", "min_price", "max_price", "min_forecast"].some((k) => params.has(k));

  return (
    <>
      <PageHeader title="Product catalog" subtitle={query.data ? `${fmtNumber(query.data.total)} products` : undefined}
        actions={
          <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && update({ view: v })} aria-label="View">
            <ToggleButton value="cards" aria-label="Card view"><GridViewIcon fontSize="small" /></ToggleButton>
            <ToggleButton value="table" aria-label="Table view"><ViewListIcon fontSize="small" /></ToggleButton>
          </ToggleButtonGroup>
        } />
      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ "&:last-child": { pb: 2 } }}>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
              <TextField size="small" fullWidth placeholder="Search by product name, SKU, brand or category" value={text}
                         onChange={(e) => setText(e.target.value)}
                         onKeyDown={(e) => e.key === "Enter" && update({ q: text.trim() || undefined, sort: undefined })}
                         onBlur={() => text.trim() !== q && update({ q: text.trim() || undefined, sort: undefined })}
                         slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
                         aria-label="Search products" />
              <TextField select size="small" label="Sort by" value={sort} sx={{ minWidth: 190 }}
                         onChange={(e) => update({ sort: e.target.value, order: undefined })}>
                {SORTS.filter((s) => s.value !== "relevance" || q).map((s) => <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>)}
              </TextField>
              {sort !== "relevance" && (
                <TextField select size="small" label="Order" value={order} sx={{ minWidth: 130 }}
                           onChange={(e) => update({ order: e.target.value })}>
                  <MenuItem value="asc">Ascending</MenuItem><MenuItem value="desc">Descending</MenuItem>
                </TextField>
              )}
            </Stack>
            <Stack direction={{ xs: "column", lg: "row" }} spacing={2} sx={{ alignItems: { lg: "center" }, flexWrap: "wrap", rowGap: 2 }}>
              <MultiSelect label="Category" value={all("category")} onChange={(v) => update({ category: v })}
                           options={filters.data?.categories.map((c) => c.value) ?? []} />
              <MultiSelect label="Brand" value={all("brand")} onChange={(v) => update({ brand: v })}
                           options={filters.data?.brands.map((c) => c.value) ?? []} />
              <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75 }} role="group" aria-label="Stock status">
                {STATUSES.map((s) => {
                  const on = all("stock_status").includes(s.value);
                  return <Chip key={s.value} label={s.label} variant={on ? "filled" : "outlined"} color={on ? "primary" : "default"}
                               onClick={() => update({ stock_status: on ? all("stock_status").filter((x) => x !== s.value) : [...all("stock_status"), s.value] })} />;
                })}
              </Stack>
              <Box sx={{ minWidth: 220, px: 1 }}>
                <Typography variant="caption" color="text.secondary">Price {fmtMoney((priceDraft ?? price)[0])} – {fmtMoney((priceDraft ?? price)[1])}</Typography>
                <Slider size="small" min={0} max={maxPrice} value={priceDraft ?? price} getAriaLabel={() => "Price range"}
                        onChange={(_, v) => setPriceDraft(v as [number, number])}
                        onChangeCommitted={(_, v) => {
                          const [lo, hi] = v as [number, number];
                          setPriceDraft(null);
                          update({ min_price: lo > 0 ? String(lo) : undefined, max_price: hi < maxPrice ? String(hi) : undefined });
                        }} />
              </Box>
              <TextField size="small" type="number" label="Min. 30-day forecast" sx={{ width: 170 }} value={get("min_forecast") ?? ""}
                         onChange={(e) => update({ min_forecast: e.target.value || undefined })} slotProps={{ htmlInput: { min: 0 } }} />
              {activeFilters && (
                <Button size="small" onClick={() => update({ category: [], brand: [], stock_status: [], min_price: undefined,
                                                           max_price: undefined, min_forecast: undefined })}>Clear filters</Button>
              )}
            </Stack>
          </Stack>
        </CardContent>
      </Card>
      {query.isFetching && query.data && <LinearProgress sx={{ mb: 1, borderRadius: 1 }} />}
      <QueryView query={query} loading={<LoadingBlock height={480} />}>
        {(data) => data.items.length === 0 ? (
          <EmptyState title="No products match" action={activeFilters || q ? <Button onClick={() => setParams({})}>Reset search</Button> : undefined}>
            Try a different name or SKU, or remove some filters.
          </EmptyState>
        ) : (
          <>
            {view === "cards" ? <CardGrid items={data.items} /> : <ProductTable items={data.items} />}
            {data.pages > 1 && (
              <Stack sx={{ mt: 3, alignItems: "center" }}>
                <Pagination count={data.pages} page={page} onChange={(_, p) => update({ page: String(p) }, false)} />
              </Stack>
            )}
          </>
        )}
      </QueryView>
    </>
  );
}

function PriceCell({ p }: { p: ProductCard }) {
  return (
    <Stack direction="row" spacing={2} divider={<Divider orientation="vertical" flexItem />}>
      <Box>
        <Typography variant="caption" color="text.secondary">Actual price</Typography>
        <Typography variant="body1" sx={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtMoney(p.current_price, true)}</Typography>
      </Box>
      <Box>
        <Typography variant="caption" color="text.secondary">Forecast price</Typography>
        {p.price_forecast_available ? (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: "baseline" }}>
            <Typography variant="body1" sx={{ fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmtMoney(p.forecast_price, true)}</Typography>
            <ChangeBadge value={p.forecast_price_change} goodWhenUp={null} />
          </Stack>
        ) : <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25 }}>Unavailable</Typography>}
      </Box>
    </Stack>
  );
}

function CardGrid({ items }: { items: ProductCard[] }) {
  return (
    <Grid container spacing={2}>
      {items.map((p) => (
        <Grid key={p.sku} size={{ xs: 12, sm: 6, lg: 4, xl: 3 }}>
          <Card sx={{ height: "100%" }}>
            <CardActionArea component={RouterLink} to={`/products/${p.sku}`} sx={{ height: "100%" }}>
              <CardContent>
                <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "flex-start", gap: 1 }}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 700 }} variant="subtitle1" noWrap title={p.name}>{p.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{p.sku} · {p.category}</Typography>
                  </Box>
                  <StockChip status={p.stock_status} />
                </Stack>
                <Box sx={{ my: 2 }}><PriceCell p={p} /></Box>
                <Stack direction="row" sx={{ justifyContent: "space-between" }}>
                  <Typography variant="body2" color="text.secondary">Stock <b>{fmtNumber(p.available_quantity)}</b> units</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {p.forecast_demand_30d !== null ? <>30-day demand <b>{fmtNumber(p.forecast_demand_30d)}</b></> : "No forecast yet"}
                  </Typography>
                </Stack>
              </CardContent>
            </CardActionArea>
          </Card>
        </Grid>
      ))}
    </Grid>
  );
}

function ProductTable({ items }: { items: ProductCard[] }) {
  const navigate = useNavigate();
  return (
    <Card sx={{ overflowX: "auto" }}>
      <Table size="small">
        <TableHead><TableRow>
          <TableCell>Product</TableCell><TableCell>Category</TableCell><TableCell>Brand</TableCell>
          <TableCell align="right">Price</TableCell><TableCell align="right">Forecast price</TableCell>
          <TableCell>Stock status</TableCell><TableCell align="right">Stock</TableCell>
          <TableCell align="right">Units, last 30d</TableCell><TableCell align="right">Forecast, next 30d</TableCell>
          <TableCell align="right">Days of cover</TableCell>
        </TableRow></TableHead>
        <TableBody>
          {items.map((p) => (
            <TableRow key={p.sku} hover sx={{ cursor: "pointer" }} onClick={() => navigate(`/products/${p.sku}`)}>
              <TableCell><Typography sx={{ fontWeight: 600 }} variant="body2">{p.name}</Typography>
                <Typography variant="caption" color="text.secondary">{p.sku}</Typography></TableCell>
              <TableCell>{p.category}</TableCell><TableCell>{p.brand}</TableCell>
              <TableCell align="right">{fmtMoney(p.current_price, true)}</TableCell>
              <TableCell align="right">{p.price_forecast_available ? fmtMoney(p.forecast_price, true) : "—"}</TableCell>
              <TableCell><StockChip status={p.stock_status} /></TableCell>
              <TableCell align="right">{fmtNumber(p.available_quantity)}</TableCell>
              <TableCell align="right">{fmtNumber(p.units_30d)}</TableCell>
              <TableCell align="right">{fmtNumber(p.forecast_demand_30d)}</TableCell>
              <TableCell align="right">{fmtNumber(p.days_of_cover, 1)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}
