import { describe, expect, it } from "vitest";
import { buildQuery } from "../api/apiClient";
import { addDays, fmtChange, fmtMoney, fmtPct, toCsv } from "./format";

describe("format helpers", () => {
  it("formats money, percentages and changes", () => {
    expect(fmtMoney(1234.5)).toBe("$1,235");
    expect(fmtMoney(79.5, true)).toBe("$79.50");
    expect(fmtMoney(null)).toBe("—");
    expect(fmtPct(0.1234)).toBe("12.3%");
    expect(fmtChange(0.031)).toBe("+3.1%");
    expect(fmtChange(-0.2)).toBe("-20.0%");
  });

  it("adds days across month ends", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("escapes CSV values", () => {
    expect(toCsv([{ a: "x,y", b: 'say "hi"', c: null }])).toBe('a,b,c\n"x,y","say ""hi""",');
  });
});

describe("buildQuery", () => {
  it("repeats array params and drops empty values", () => {
    expect(buildQuery({ q: "coffee", category: ["Home", "Sports"], brand: [], page: 2, x: undefined, y: "" }))
      .toBe("?q=coffee&category=Home&category=Sports&page=2");
  });
});
