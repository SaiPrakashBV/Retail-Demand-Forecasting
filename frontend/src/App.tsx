import { CssBaseline, ThemeProvider } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/apiClient";
import Layout from "./components/Layout";
import { EmptyState, LoadingBlock } from "./components/StateViews";
import { buildTheme } from "./theme";

const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const ProductsPage = lazy(() => import("./pages/ProductsPage"));
const ProductDetailsPage = lazy(() => import("./pages/ProductDetailsPage"));
const ForecastPage = lazy(() => import("./pages/ForecastPage"));
const InventoryPage = lazy(() => import("./pages/InventoryPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const PipelineStatusPage = lazy(() => import("./pages/PipelineStatusPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // Do not retry "not available yet" or "not found": they will not change by retrying.
      retry: (count, error) => !(error instanceof ApiError && [400, 401, 404, 409, 422, 503].includes(error.status)) && count < 2,
    },
  },
});

function readMode(): "light" | "dark" {
  try {
    const saved = localStorage.getItem("theme-mode");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [mode, setMode] = useState<"light" | "dark">(readMode);
  const theme = useMemo(() => buildTheme(mode), [mode]);
  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    try {
      localStorage.setItem("theme-mode", mode);
    } catch {
      /* storage unavailable */
    }
  }, [mode]);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter>
          <Layout mode={mode} onToggleMode={() => setMode((m) => (m === "dark" ? "light" : "dark"))}>
            <Suspense fallback={<LoadingBlock height={400} />}>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/products/:sku" element={<ProductDetailsPage />} />
              <Route path="/forecasts" element={<ForecastPage />} />
              <Route path="/inventory" element={<InventoryPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/pipelines" element={<PipelineStatusPage />} />
              <Route path="*" element={<EmptyState title="Page not found">Use the navigation to find what you need.</EmptyState>} />
            </Routes>
            </Suspense>
          </Layout>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
