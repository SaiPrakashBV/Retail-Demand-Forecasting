import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutlineOutlined";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutlineOutlined";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import RemoveCircleOutlineIcon from "@mui/icons-material/RemoveCircleOutlineOutlined";
import ReportProblemOutlinedIcon from "@mui/icons-material/ReportProblemOutlined";
import { Box, Card, CardContent, Chip, Stack, Tooltip, Typography } from "@mui/material";
import type { ReactNode } from "react";
import type { Priority, StockStatus } from "../api/types";
import { useChartColors } from "../theme";
import { fmtChange } from "../utils/format";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 3, alignItems: { sm: "flex-end" }, justifyContent: "space-between" }}>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="h4" component="h1">{title}</Typography>
        {subtitle && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{subtitle}</Typography>}
      </Box>
      {actions && <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>{actions}</Stack>}
    </Stack>
  );
}

export function Section({ title, subtitle, action, children }: { title: string; subtitle?: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <CardContent sx={{ p: { xs: 2, md: 2.5 }, "&:last-child": { pb: { xs: 2, md: 2.5 } } }}>
        <Stack direction="row" sx={{ mb: 2, alignItems: "flex-start", justifyContent: "space-between", gap: 1 }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h6" component="h2" sx={{ fontSize: 16 }}>{title}</Typography>
            {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
          </Box>
          {action}
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}

/** Change badge. ``goodWhenUp=null`` = neutral (a change in demand is not good or bad by itself). */
export function ChangeBadge({ value, goodWhenUp = true, suffix }: { value: number | null | undefined; goodWhenUp?: boolean | null; suffix?: string }) {
  const c = useChartColors();
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  value = Math.round(value * 1000) / 1000; // avoid "-0.0%" for tiny changes
  if (Object.is(value, -0)) value = 0;
  const up = value > 0;
  const color = goodWhenUp === null || value === 0 ? c.text2 : (up === goodWhenUp ? c.status.good : c.status.critical);
  const Icon = up ? ArrowUpwardIcon : ArrowDownwardIcon;
  return (
    <Stack direction="row" spacing={0.25} sx={{ alignItems: "center", color }}>
      {value !== 0 && <Icon sx={{ fontSize: 14 }} />}
      <Typography sx={{ fontWeight: 600 }} variant="caption" color="inherit">{fmtChange(value)}{suffix ? ` ${suffix}` : ""}</Typography>
    </Stack>
  );
}

export function KpiCard({ label, value, change, goodWhenUp = true, changeLabel, hint, icon }: {
  label: string; value: ReactNode; change?: number | null; goodWhenUp?: boolean | null; changeLabel?: string;
  hint?: ReactNode; icon?: ReactNode;
}) {
  return (
    <Card sx={{ height: "100%" }}>
      <CardContent sx={{ p: 2.25, "&:last-child": { pb: 2.25 } }}>
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", color: "text.secondary" }}>
          <Typography sx={{ fontWeight: 500 }} variant="body2" color="text.secondary">{label}</Typography>
          {icon}
        </Stack>
        <Typography variant="h5" sx={{ mt: 1, fontVariantNumeric: "tabular-nums" }}>{value}</Typography>
        <Stack direction="row" spacing={0.75} sx={{ mt: 0.5, alignItems: "center", minHeight: 20, flexWrap: "wrap" }}>
          <ChangeBadge value={change} goodWhenUp={goodWhenUp} suffix={changeLabel} />
          {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
        </Stack>
      </CardContent>
    </Card>
  );
}

const STOCK: Record<StockStatus, { label: string; icon: ReactNode; key: "good" | "warning" | "critical" }> = {
  in_stock: { label: "In stock", icon: <CheckCircleOutlineIcon />, key: "good" },
  low_stock: { label: "Low stock", icon: <ReportProblemOutlinedIcon />, key: "warning" },
  out_of_stock: { label: "Out of stock", icon: <RemoveCircleOutlineIcon />, key: "critical" },
};

export function StockChip({ status, size = "small" }: { status: StockStatus; size?: "small" | "medium" }) {
  const c = useChartColors();
  const s = STOCK[status];
  return <Chip size={size} icon={s.icon as React.ReactElement} label={s.label} variant="outlined"
               sx={{ color: c.status[s.key], borderColor: c.status[s.key], "& .MuiChip-icon": { color: "inherit" } }} />;
}

const PRIORITY: Record<Priority, { key: "critical" | "serious" | "warning" | "good"; icon: ReactNode; label: string }> = {
  critical: { key: "critical", icon: <ErrorOutlineIcon />, label: "Critical" },
  high: { key: "serious", icon: <ReportProblemOutlinedIcon />, label: "High" },
  medium: { key: "warning", icon: <HourglassEmptyIcon />, label: "Medium" },
  low: { key: "good", icon: <CheckCircleOutlineIcon />, label: "Low" },
};

export function PriorityChip({ priority }: { priority: Priority | null | undefined }) {
  const c = useChartColors();
  if (!priority) return <Typography variant="caption" color="text.secondary">—</Typography>;
  const p = PRIORITY[priority];
  return <Chip size="small" icon={p.icon as React.ReactElement} label={p.label} variant="outlined"
               sx={{ color: c.status[p.key], borderColor: c.status[p.key], "& .MuiChip-icon": { color: "inherit" } }} />;
}

export function RunStatusChip({ status }: { status: string }) {
  const c = useChartColors();
  const map: Record<string, { key: "good" | "warning" | "critical"; icon: ReactNode; label: string }> = {
    succeeded: { key: "good", icon: <CheckCircleOutlineIcon />, label: "Succeeded" },
    running: { key: "warning", icon: <HourglassEmptyIcon />, label: "Running" },
    queued: { key: "warning", icon: <HourglassEmptyIcon />, label: "Queued" },
    failed: { key: "critical", icon: <ErrorOutlineIcon />, label: "Failed" },
  };
  const s = map[status] ?? { key: "warning", icon: <HourglassEmptyIcon />, label: status };
  return <Chip size="small" icon={s.icon as React.ReactElement} label={s.label} variant="outlined"
               sx={{ color: c.status[s.key], borderColor: c.status[s.key], "& .MuiChip-icon": { color: "inherit" } }} />;
}

export function LabelValue({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Box>
      <Tooltip title={hint ?? ""} disableHoverListener={!hint}>
        <Typography variant="caption" color="text.secondary" sx={{ cursor: hint ? "help" : undefined }}>{label}</Typography>
      </Tooltip>
      <Typography variant="body1" sx={{ fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{value}</Typography>
    </Box>
  );
}
