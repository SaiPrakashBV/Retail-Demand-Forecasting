import SearchIcon from "@mui/icons-material/Search";
import { Autocomplete, Box, InputAdornment, TextField, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/apiClient";
import type { ProductCard } from "../api/types";
import { fmtMoney } from "../utils/format";

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Global search: matches SKU, name, brand or category; Enter opens the full catalog search. */
export default function ProductSearch({ fullWidth = false }: { fullWidth?: boolean }) {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const q = useDebounced(input.trim());
  const { data, isFetching } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.products({ q, page_size: 8, sort: "relevance" }),
    enabled: q.length >= 2,
    staleTime: 30_000,
  });
  const options: ProductCard[] = q.length >= 2 ? data?.items ?? [] : [];

  return (
    <Autocomplete<ProductCard, false, false, true>
      freeSolo
      fullWidth
      sx={{ width: "100%", maxWidth: fullWidth ? undefined : 460 }}
      options={options}
      loading={isFetching}
      filterOptions={(x) => x}
      inputValue={input}
      onInputChange={(_, v) => setInput(v)}
      getOptionLabel={(o) => (typeof o === "string" ? o : `${o.name} (${o.sku})`)}
      noOptionsText={q.length < 2 ? "Type at least 2 characters" : "No matching products"}
      onChange={(_, value) => {
        if (!value) return;
        if (typeof value === "string") navigate(`/products?q=${encodeURIComponent(value)}`);
        else navigate(`/products/${encodeURIComponent(value.sku)}`);
        setInput("");
      }}
      renderOption={(props, o) => {
        const { key, ...rest } = props as typeof props & { key: string };
        return (
          <Box component="li" key={key} {...rest} sx={{ display: "flex", justifyContent: "space-between", gap: 2 }}>
            <Box sx={{ minWidth: 0 }}>
              <Typography sx={{ fontWeight: 600 }} variant="body2" noWrap>{o.name}</Typography>
              <Typography variant="caption" color="text.secondary">{o.sku} · {o.category} · {o.brand}</Typography>
            </Box>
            <Typography variant="body2" sx={{ ml: "auto", pl: 2, fontVariantNumeric: "tabular-nums" }}>{fmtMoney(o.current_price, true)}</Typography>
          </Box>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          size="small"
          placeholder="Search products by name or SKU"
          aria-label="Search products by name or SKU"
          slotProps={{
            ...params.slotProps,
            input: {
              ...params.slotProps.input,
              startAdornment: (
                <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>
              ),
            },
          }}
        />
      )}
    />
  );
}
