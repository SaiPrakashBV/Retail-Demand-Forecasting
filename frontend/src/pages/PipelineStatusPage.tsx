import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import {
  Alert, Box, Button, Chip, Dialog, DialogContent, DialogTitle, Grid, Stack, Table, TableBody, TableCell, TableHead,
  TableRow, Typography,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/apiClient";
import type { PipelineStatus } from "../api/types";
import { KpiCard, PageHeader, RunStatusChip, Section } from "../components/Common";
import { EmptyState, LoadingBlock, QueryView } from "../components/StateViews";
import { fmtDate, fmtDateTime, fmtNumber, titleCase } from "../utils/format";

export default function PipelineStatusPage() {
  const status = useQuery({ queryKey: ["pipeline-status"], queryFn: api.pipelineStatus, refetchInterval: 15_000 });
  return (
    <>
      <PageHeader title="Pipeline status" subtitle="Data ingestion (Airflow retail_etl) and forecasting jobs"
        actions={status.data && <>
          <Button variant="outlined" endIcon={<OpenInNewIcon />} href={status.data.links.airflow} target="_blank" rel="noreferrer">Airflow</Button>
          <Button variant="outlined" endIcon={<OpenInNewIcon />} href={status.data.links.mlflow} target="_blank" rel="noreferrer">MLflow</Button>
        </>} />
      <QueryView query={status} loading={<LoadingBlock height={400} />}>
        {(s) => <StatusBody s={s} />}
      </QueryView>
    </>
  );
}

function StatusBody({ s }: { s: PipelineStatus }) {
  const [quarantineRun, setQuarantineRun] = useState<string | null>(null);
  const f = s.freshness;
  const lastRun = s.ingestion_runs[0];
  return (
    <Stack spacing={3}>
      {!f.data_end && (
        <Alert severity="warning" variant="outlined">
          No sales data has been loaded yet. The retail_etl DAG runs daily at 01:00 UTC and once when the stack first starts;
          you can also trigger it from the Airflow UI.
        </Alert>
      )}
      {lastRun?.status === "failed" && (
        <Alert severity="error" variant="outlined">
          The latest ingestion run failed {fmtDateTime(lastRun.end_time)} and loaded nothing: {lastRun.error}
        </Alert>
      )}
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="Latest sales date" value={fmtDate(f.data_end)}
                   hint={f.data_end ? (f.is_stale ? <Chip size="small" color="warning" variant="outlined" label={`Stale: ${fmtNumber(f.hours_since_data_end)} h old`} />
                                       : `${fmtNumber(f.hours_since_data_end)} h ago`) : "Nothing loaded"} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="Last successful ingestion" value={fmtDateTime(f.last_successful_ingestion)} hint={f.data_start ? `History from ${fmtDate(f.data_start)}` : undefined} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="Latest forecast" value={fmtDateTime(f.latest_forecast_at)}
                   hint={f.latest_forecast_cutoff ? `Uses data up to ${fmtDate(f.latest_forecast_cutoff)}` : "Not generated yet"} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard label="Rows in database" value={fmtNumber(Object.values(s.table_counts).reduce((a, b) => a + b, 0))}
                   hint={`${fmtNumber(s.table_counts.sales_transactions)} sales · ${fmtNumber(s.table_counts.forecasts)} forecasts`} />
        </Grid>
      </Grid>

      <Section title="Ingestion runs" subtitle="Extract → clean → validate → transform → load">
        {s.ingestion_runs.length ? (
          <Box sx={{ overflowX: "auto" }}>
            <Table size="small">
              <TableHead><TableRow><TableCell>Started</TableCell><TableCell>Run</TableCell><TableCell>Status</TableCell>
                <TableCell align="right">Duration</TableCell><TableCell align="right">Extracted</TableCell>
                <TableCell align="right">Loaded</TableCell><TableCell align="right">Quarantined</TableCell><TableCell>Notes</TableCell></TableRow></TableHead>
              <TableBody>
                {s.ingestion_runs.map((r) => (
                  <TableRow key={r.pipeline_id} hover>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDateTime(r.start_time)}</TableCell>
                    <TableCell sx={{ maxWidth: 220 }}><Typography variant="caption" noWrap sx={{ display: "block" }} title={r.pipeline_id}>{r.pipeline_id}</Typography></TableCell>
                    <TableCell><RunStatusChip status={r.status} /></TableCell>
                    <TableCell align="right">{r.duration_seconds !== null ? `${Math.round(r.duration_seconds)} s` : "—"}</TableCell>
                    <TableCell align="right">{fmtNumber(r.records_extracted)}</TableCell>
                    <TableCell align="right">{fmtNumber(r.records_processed)}</TableCell>
                    <TableCell align="right">
                      {r.records_quarantined ? <Button size="small" onClick={() => setQuarantineRun(r.pipeline_id)}>{fmtNumber(r.records_quarantined)}</Button> : 0}
                    </TableCell>
                    <TableCell sx={{ maxWidth: 360 }}><Typography variant="caption" color={r.error ? "error" : "text.secondary"}>{r.error ?? (r.critical?.length ? r.critical.join("; ") : "")}</Typography></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        ) : <EmptyState title="No ingestion runs yet">The first retail_etl run starts automatically after Airflow comes up.</EmptyState>}
      </Section>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 6 }}>
          <Section title="Quarantined records, latest run" subtitle="Rejected by data-quality rules; valid records were still loaded">
            {s.latest_quarantine.length ? (
              <Table size="small">
                <TableHead><TableRow><TableCell>Entity</TableCell><TableCell>Reason</TableCell><TableCell align="right">Records</TableCell></TableRow></TableHead>
                <TableBody>
                  {s.latest_quarantine.map((q) => (
                    <TableRow key={q.entity + q.reason}><TableCell>{titleCase(q.entity)}</TableCell><TableCell>{q.reason}</TableCell>
                      <TableCell align="right">{fmtNumber(q.count)}</TableCell></TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : <EmptyState title="Nothing quarantined in the latest run" />}
          </Section>
        </Grid>
        <Grid size={{ xs: 12, lg: 6 }}>
          <Section title="Forecast training jobs">
            {s.forecast_jobs.length ? (
              <Table size="small">
                <TableHead><TableRow><TableCell>Requested</TableCell><TableCell>By</TableCell><TableCell>Status</TableCell><TableCell>Result</TableCell></TableRow></TableHead>
                <TableBody>
                  {s.forecast_jobs.slice(0, 6).map((j) => (
                    <TableRow key={j.job_id}><TableCell sx={{ whiteSpace: "nowrap" }}>{fmtDateTime(j.requested_at)}</TableCell>
                      <TableCell sx={{ maxWidth: 140 }}><Typography variant="caption" noWrap sx={{ display: "block" }}>{j.requested_by}</Typography></TableCell>
                      <TableCell><RunStatusChip status={j.status} /></TableCell>
                      <TableCell><Typography variant="caption" color={j.error ? "error" : "text.secondary"}>{j.error ?? j.message ?? `${j.progress}%`}</Typography></TableCell></TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : <EmptyState title="No training jobs yet" />}
          </Section>
        </Grid>
      </Grid>
      <QuarantineDialog pipelineId={quarantineRun} onClose={() => setQuarantineRun(null)} />
    </Stack>
  );
}

function QuarantineDialog({ pipelineId, onClose }: { pipelineId: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["quarantine", pipelineId], queryFn: () => api.quarantine(pipelineId!, 100), enabled: !!pipelineId });
  return (
    <Dialog open={!!pipelineId} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Quarantined records (first 100)</DialogTitle>
      <DialogContent>
        <QueryView query={q} loading={<LoadingBlock lines={6} />}>
          {(rows) => (
            <Table size="small">
              <TableHead><TableRow><TableCell>Entity</TableCell><TableCell>Reason</TableCell><TableCell>Record as received</TableCell></TableRow></TableHead>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.quarantine_id}><TableCell>{titleCase(r.entity)}</TableCell><TableCell>{r.reason}</TableCell>
                    <TableCell><Typography variant="caption" component="code" sx={{ fontFamily: "monospace", wordBreak: "break-all" }}>{JSON.stringify(r.record)}</Typography></TableCell></TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </QueryView>
      </DialogContent>
    </Dialog>
  );
}
