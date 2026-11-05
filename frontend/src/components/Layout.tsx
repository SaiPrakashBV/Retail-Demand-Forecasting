import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import Inventory2OutlinedIcon from "@mui/icons-material/Inventory2Outlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import MenuIcon from "@mui/icons-material/Menu";
import SettingsInputComponentOutlinedIcon from "@mui/icons-material/SettingsInputComponentOutlined";
import ShowChartIcon from "@mui/icons-material/ShowChart";
import StorefrontOutlinedIcon from "@mui/icons-material/StorefrontOutlined";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import {
  AppBar, Box, Chip, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Toolbar, Tooltip,
  Typography, useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { api } from "../api/apiClient";
import { fmtDate } from "../utils/format";
import ProductSearch from "./ProductSearch";

const DRAWER = 232;
const NAV = [
  { to: "/", label: "Dashboard", icon: <DashboardOutlinedIcon /> },
  { to: "/products", label: "Products", icon: <StorefrontOutlinedIcon /> },
  { to: "/forecasts", label: "Forecasts", icon: <ShowChartIcon /> },
  { to: "/inventory", label: "Inventory", icon: <Inventory2OutlinedIcon /> },
  { to: "/reports", label: "Reports", icon: <AssessmentOutlinedIcon /> },
  { to: "/pipelines", label: "Pipeline status", icon: <SettingsInputComponentOutlinedIcon /> },
];

function Freshness() {
  const { data } = useQuery({ queryKey: ["pipeline-status"], queryFn: api.pipelineStatus, refetchInterval: 60_000 });
  if (!data) return null;
  const f = data.freshness;
  if (!f.data_end) {
    return <Chip size="small" color="warning" variant="outlined" icon={<WarningAmberIcon />} label="No data loaded yet"
                 component={NavLink} to="/pipelines" clickable />;
  }
  return (
    <Tooltip title={f.is_stale ? `Latest sales data is ${f.hours_since_data_end} hours old` : "Latest sales date loaded"}>
      <Chip size="small" variant="outlined" component={NavLink} to="/pipelines" clickable
            color={f.is_stale ? "warning" : "default"} icon={f.is_stale ? <WarningAmberIcon /> : undefined}
            label={`Data to ${fmtDate(f.data_end, { month: "short", day: "numeric" })}`} />
    </Tooltip>
  );
}

export default function Layout({ children, mode, onToggleMode }: { children: ReactNode; mode: "light" | "dark"; onToggleMode: () => void }) {
  const theme = useTheme();
  const desktop = useMediaQuery(theme.breakpoints.up("md"));
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const isActive = (to: string) => (to === "/" ? location.pathname === "/" : location.pathname.startsWith(to));

  const nav = (
    <Box sx={{ width: DRAWER }}>
      <Toolbar sx={{ gap: 1 }}>
        <Box component="img" src="/favicon.svg" alt="" sx={{ width: 28, height: 28 }} />
        <Typography sx={{ fontWeight: 700 }} variant="subtitle1" noWrap>Retail Analytics</Typography>
      </Toolbar>
      <List sx={{ px: 1 }}>
        {NAV.map((n) => (
          <ListItemButton key={n.to} component={NavLink} to={n.to} selected={isActive(n.to)} onClick={() => setOpen(false)}
                          sx={{ borderRadius: 2, mb: 0.5 }}>
            <ListItemIcon sx={{ minWidth: 36 }}>{n.icon}</ListItemIcon>
            <ListItemText primary={n.label} />
          </ListItemButton>
        ))}
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="fixed" color="inherit" elevation={0}
              sx={{ borderBottom: 1, borderColor: "divider", width: { md: `calc(100% - ${DRAWER}px)` }, ml: { md: `${DRAWER}px` } }}>
        <Toolbar sx={{ gap: 1.5 }}>
          {!desktop && (
            <IconButton edge="start" onClick={() => setOpen(true)} aria-label="Open navigation"><MenuIcon /></IconButton>
          )}
          <Box sx={{ flex: 1, minWidth: 0, display: "flex" }}><ProductSearch /></Box>
          <Box sx={{ display: { xs: "none", sm: "block" } }}><Freshness /></Box>
          <Tooltip title={mode === "dark" ? "Light mode" : "Dark mode"}>
            <IconButton onClick={onToggleMode} aria-label="Toggle colour theme">
              {mode === "dark" ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box component="nav" sx={{ width: { md: DRAWER }, flexShrink: { md: 0 } }}>
        {desktop ? (
          <Drawer variant="permanent" open sx={{ "& .MuiDrawer-paper": { width: DRAWER, boxSizing: "border-box" } }}>{nav}</Drawer>
        ) : (
          <Drawer variant="temporary" open={open} onClose={() => setOpen(false)} ModalProps={{ keepMounted: true }}>{nav}</Drawer>
        )}
      </Box>
      <Box component="main" sx={{ flex: 1, minWidth: 0, px: { xs: 2, md: 4 }, py: 3, mt: 8 }}>
        {children}
      </Box>
    </Box>
  );
}
