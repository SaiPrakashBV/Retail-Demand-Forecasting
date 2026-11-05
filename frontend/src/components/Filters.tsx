import { MenuItem, TextField } from "@mui/material";

/** Multi-value select; an empty selection means "all". */
export function MultiSelect({ label, value, onChange, options, minWidth = 180 }: {
  label: string; value: string[]; onChange: (v: string[]) => void; options: string[]; minWidth?: number;
}) {
  return (
    <TextField select size="small" label={label} sx={{ minWidth }}
               value={value} onChange={(e) => onChange(typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value as string[])}
               slotProps={{ select: { multiple: true, renderValue: (v) => ((v as string[]).length ? (v as string[]).join(", ") : "All") , displayEmpty: true },
                            inputLabel: { shrink: true } }}>
      {options.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
    </TextField>
  );
}
