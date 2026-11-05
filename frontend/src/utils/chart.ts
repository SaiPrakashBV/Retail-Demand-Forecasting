import { useChartColors } from "../theme";
import { fmtDate } from "./format";

export const tickDate = (v: string) => fmtDate(v, { month: "short", day: "numeric" });
export const tickMonth = (v: string) => fmtDate(v, { month: "short", year: "2-digit" });

export function useAxisProps() {
  const c = useChartColors();
  return {
    axis: { stroke: c.grid, tick: { fill: c.text2, fontSize: 12 }, tickLine: false },
    grid: { stroke: c.grid, strokeDasharray: "0", vertical: false },
  };
}
