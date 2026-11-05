// Thin client over the FastAPI backend. Errors carry the API's readable message.
import type {
  AccuracyReport, Dashboard, FilterOptions, ForecastComparisonData, PipelineStatus, Portfolio, ProductDetail,
  ProductForecast, ProductInventory, ProductPage, PriceHistory, QuarantineRecord, ReorderList, ReportInfo,
  ReportPreview, SalesHistory, TrainingJob,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Data or a forecast simply does not exist yet: show guidance, not a failure. */
  get isUnavailable(): boolean {
    return this.status === 503 && /unavailable|not_ready/.test(this.code) && this.code !== "database_unavailable";
  }
}

type Params = Record<string, string | number | boolean | string[] | null | undefined>;

export function buildQuery(params: Params = {}): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => q.append(key, v));
    else q.append(key, String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function apiUrl(path: string, params?: Params): string {
  return `${API_BASE}${path}${buildQuery(params)}`;
}

async function request<T>(path: string, init?: RequestInit & { params?: Params }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path, init?.params), {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the API. Check that the backend service is running.");
  }
  if (!res.ok) {
    let body: { error?: { code?: string; message?: string; details?: Record<string, unknown> } } = {};
    try {
      body = await res.json();
    } catch {
      /* non-JSON error page (e.g. proxy) */
    }
    const e = body.error;
    throw new ApiError(res.status, e?.code ?? "http_error",
      e?.message ?? `The server returned HTTP ${res.status}${res.status === 502 ? " (API not reachable)" : ""}.`,
      e?.details ?? {});
  }
  return (await res.json()) as T;
}

export interface ProductQuery {
  q?: string;
  category?: string[];
  brand?: string[];
  stock_status?: string[];
  min_price?: number;
  max_price?: number;
  min_forecast?: number;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export const api = {
  products: (q: ProductQuery) => request<ProductPage>("/api/products", { params: { ...q } }),
  productFilters: () => request<FilterOptions>("/api/products/filters"),
  product: (sku: string) => request<ProductDetail>(`/api/products/${encodeURIComponent(sku)}`),
  productSales: (sku: string, params: { start?: string; end?: string; granularity?: string }) =>
    request<SalesHistory>(`/api/products/${encodeURIComponent(sku)}/sales`, { params }),
  productPrices: (sku: string, params: { start?: string; end?: string }) =>
    request<PriceHistory>(`/api/products/${encodeURIComponent(sku)}/prices`, { params }),
  productForecast: (sku: string, runId?: string) =>
    request<ProductForecast>(`/api/products/${encodeURIComponent(sku)}/forecast`, { params: { run_id: runId } }),
  productComparison: (sku: string, runId?: string) =>
    request<ForecastComparisonData>(`/api/products/${encodeURIComponent(sku)}/forecast-comparison`,
      { params: { run_id: runId } }),
  productInventory: (sku: string, days = 120) =>
    request<ProductInventory>(`/api/products/${encodeURIComponent(sku)}/inventory`, { params: { days } }),
  dashboard: (params: { start?: string; end?: string; category?: string[]; brand?: string[] }) =>
    request<Dashboard>("/api/analytics/dashboard", { params }),
  accuracy: (params: { sku?: string; category?: string[] } = {}) =>
    request<AccuracyReport>("/api/analytics/accuracy", { params }),
  portfolio: (category?: string[]) => request<Portfolio>("/api/forecasts/portfolio", { params: { category } }),
  jobs: () => request<TrainingJob[]>("/api/forecasts/jobs"),
  job: (id: string) => request<TrainingJob>(`/api/forecasts/jobs/${id}`),
  train: (apiKey: string, body: { requested_by: string; reason?: string }) =>
    request<TrainingJob>("/api/forecasts/train", {
      method: "POST", body: JSON.stringify(body), headers: { "X-API-Key": apiKey },
    }),
  reorders: (params: { priority?: string[]; category?: string[]; q?: string; actionable_only?: boolean; sort?: string;
                       page?: number; page_size?: number }) => request<ReorderList>("/api/inventory/reorders", { params }),
  reports: () => request<ReportInfo[]>("/api/reports"),
  reportPreview: (id: string, params: Params) => request<ReportPreview>(`/api/reports/${id}`, { params: { ...params, format: "json" } }),
  reportDownloadUrl: (id: string, format: "csv" | "xlsx", params: Params) => apiUrl(`/api/reports/${id}`, { ...params, format }),
  pipelineStatus: () => request<PipelineStatus>("/api/pipelines/status"),
  quarantine: (pipelineId: string, limit = 50) =>
    request<QuarantineRecord[]>(`/api/pipelines/runs/${encodeURIComponent(pipelineId)}/quarantine`, { params: { limit } }),
};
