import RefreshIcon from "@mui/icons-material/Refresh";
import { Alert, AlertTitle, Box, Button, Paper, Skeleton, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { ApiError } from "../api/apiClient";

export function LoadingBlock({ height = 240, lines = 0 }: { height?: number; lines?: number }) {
  return (
    <Stack spacing={1} aria-busy="true" aria-label="Loading">
      {lines > 0
        ? Array.from({ length: lines }).map((_, i) => <Skeleton key={i} variant="rounded" height={36} />)
        : <Skeleton variant="rounded" height={height} />}
    </Stack>
  );
}

/** Explains *why* something is missing instead of rendering an empty chart. */
export function ErrorState({ error, onRetry, title }: { error: unknown; onRetry?: () => void; title?: string }) {
  const e = error instanceof ApiError ? error : null;
  if (e?.isUnavailable) {
    return (
      <Alert severity="info" variant="outlined">
        <AlertTitle>{title ?? "Not available yet"}</AlertTitle>
        {e.message}
      </Alert>
    );
  }
  return (
    <Alert severity="error" variant="outlined"
           action={onRetry && <Button color="inherit" size="small" startIcon={<RefreshIcon />} onClick={onRetry}>Retry</Button>}>
      <AlertTitle>{title ?? "Something went wrong"}</AlertTitle>
      {e?.message ?? (error instanceof Error ? error.message : "Unexpected error")}
    </Alert>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ p: 4, textAlign: "center", borderStyle: "dashed" }}>
      <Typography sx={{ fontWeight: 600 }} variant="subtitle1">{title}</Typography>
      {children && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 520, mx: "auto" }}>{children}</Typography>}
      {action && <Box sx={{ mt: 2 }}>{action}</Box>}
    </Paper>
  );
}

interface QueryLike<T> {
  data: T | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => unknown;
}

/** Render loading / error / data states for a react-query result. */
export function QueryView<T>({ query, children, loading, errorTitle }: {
  query: QueryLike<T>; children: (data: T) => ReactNode; loading?: ReactNode; errorTitle?: string;
}) {
  if (query.isLoading) return <>{loading ?? <LoadingBlock />}</>;
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} title={errorTitle} />;
  if (query.data === undefined) return null;
  return <>{children(query.data)}</>;
}
