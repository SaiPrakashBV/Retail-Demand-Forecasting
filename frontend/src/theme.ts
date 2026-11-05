import { createTheme, type PaletteMode, type Theme, useTheme } from "@mui/material/styles";

// Validated categorical palette (fixed order; colour follows the entity, never its rank).
const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};
const TOKENS = {
  light: { surface: "#fcfcfb", paper: "#ffffff", text: "#0b0b0b", text2: "#52514e", muted: "#7a7974", grid: "#e4e3df",
           border: "#e4e3df", bg: "#f4f3f0" },
  dark: { surface: "#1a1a19", paper: "#212120", text: "#f0efec", text2: "#c3c2b7", muted: "#93928b", grid: "#33322f",
          border: "#33322f", bg: "#141413" },
};
// Status colours are reserved for state and always ship with an icon/label.
const STATUS = {
  light: { good: "#1e7a4f", warning: "#b26b00", serious: "#c2410c", critical: "#c62828" },
  dark: { good: "#4cc38a", warning: "#e0a030", serious: "#f0814a", critical: "#ef6b6b" },
};

export function buildTheme(mode: PaletteMode): Theme {
  const t = TOKENS[mode];
  return createTheme({
    palette: {
      mode,
      primary: { main: SERIES[mode][0] },
      secondary: { main: SERIES[mode][1] },
      success: { main: STATUS[mode].good },
      warning: { main: STATUS[mode].warning },
      error: { main: STATUS[mode].critical },
      background: { default: t.bg, paper: t.paper },
      text: { primary: t.text, secondary: t.text2 },
      divider: t.border,
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily: '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      h4: { fontWeight: 700, letterSpacing: -0.5 },
      h5: { fontWeight: 700, letterSpacing: -0.3 },
      h6: { fontWeight: 650 },
      subtitle2: { fontWeight: 600 },
      button: { textTransform: "none", fontWeight: 600 },
    },
    components: {
      MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { backgroundImage: "none" } } },
      MuiCard: { styleOverrides: { root: { border: `1px solid ${t.border}` } } },
      MuiTableCell: { styleOverrides: { head: { fontWeight: 600, color: t.text2 } } },
      MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    },
  });
}

export interface ChartColors {
  actual: string;
  forecast: string;
  band: string;
  baseline: string;
  series: string[];
  grid: string;
  text: string;
  text2: string;
  surface: string;
  status: typeof STATUS.light;
}

export function chartColors(mode: PaletteMode): ChartColors {
  const t = TOKENS[mode];
  return {
    actual: SERIES[mode][0],
    forecast: SERIES[mode][1],
    band: SERIES[mode][1],
    baseline: t.muted,
    series: SERIES[mode],
    grid: t.grid,
    text: t.text,
    text2: t.text2,
    surface: t.surface,
    status: STATUS[mode],
  };
}

export function useChartColors(): ChartColors {
  return chartColors(useTheme().palette.mode);
}

/** Stable colour per category: slot order is alphabetical over all categories. */
export function categoryColor(all: string[], category: string, colors: ChartColors): string {
  const i = [...all].sort().indexOf(category);
  return colors.series[(i < 0 ? 0 : i) % colors.series.length];
}
