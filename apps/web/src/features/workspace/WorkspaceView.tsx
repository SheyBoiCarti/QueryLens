import React, { useEffect, useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionResponse, PublicRun } from '../../api/generated/schema.ts';
import { QuestionForm } from './QuestionForm.tsx';
import { QueryStatus } from './QueryStatus.tsx';
import { ResultsTable } from './ResultsTable.tsx';
import { SQLPanel } from './SQLPanel.tsx';
import { Assumptions } from './Assumptions.tsx';
import { QueryInspector, TraceData } from './QueryInspector.tsx';

interface WorkspaceViewProps {
  onNavigateToConnections: () => void;
  initialQueryId?: string | null;
  onActiveQueryChange?: (id: string | null) => void;
}

const terminal = new Set(['completed', 'failed', 'rejected', 'clarification_required', 'cancelled', 'interrupted']);

export function WorkspaceView({ onNavigateToConnections, initialQueryId, onActiveQueryChange }: WorkspaceViewProps): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [connectionId, setConnectionId] = useState('');
  const [connectionsError, setConnectionsError] = useState<string | null>(null);
  const [loadingConnections, setLoadingConnections] = useState(true);
  const [activeQueryId, setActiveQueryId] = useState<string | null>(initialQueryId || null);
  const [query, setQuery] = useState<PublicRun | null>(null);
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    api.get<ConnectionResponse[]>('/api/v1/connections', { signal: abort.signal })
      .then((items) => { setConnections(items); setConnectionId(items[0]?.id || ''); })
      .catch((err: unknown) => { if (!abort.signal.aborted) setConnectionsError(err instanceof Error ? err.message : 'Could not load connections'); })
      .finally(() => { if (!abort.signal.aborted) setLoadingConnections(false); });
    return () => abort.abort();
  }, []);

  useEffect(() => {
    if (!activeQueryId) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const poll = async () => {
      try {
        const run = await api.get<PublicRun>(`/api/v1/queries/${activeQueryId}`, { signal: abort.signal });
        if (abort.signal.aborted) return;
        setConnectionId(run.connection_id);
        setQuery((previous) => previous && previous.state_version > run.state_version ? previous : run);
        setPollError(null);
        failures = 0;
        if (terminal.has(run.status)) {
          setCancelling(false);
          try {
            const data = await api.get<TraceData>(`/api/v1/queries/${activeQueryId}/trace`, { signal: abort.signal });
            if (!abort.signal.aborted) setTrace(data);
          } catch { /* Results remain usable when diagnostics are unavailable. */ }
          return;
        }
      } catch (err) {
        if (abort.signal.aborted) return;
        failures += 1;
        setPollError(err instanceof Error ? err.message : 'Could not refresh query status');
        if (err instanceof ApiError && [401, 403, 404].includes(err.statusCode)) return;
      }
      if (!abort.signal.aborted) timer = setTimeout(() => void poll(), Math.min(30000, 1000 * 2 ** failures));
    };
    void poll();
    return () => { abort.abort(); if (timer) clearTimeout(timer); };
  }, [activeQueryId, retry]);

  const submitted = (id: string) => {
    setActiveQueryId(id);
    onActiveQueryChange?.(id);
    setQuery(null);
    setTrace(null);
    setInspecting(false);
    setPollError(null);
  };

  const cancel = async () => {
    if (!activeQueryId) return;
    setCancelling(true);
    try {
      await api.post(`/api/v1/queries/${activeQueryId}/cancel`);
      setRetry((value) => value + 1);
    } catch (err) {
      setPollError(err instanceof Error ? err.message : 'Cancellation failed; please retry');
      setCancelling(false);
    }
  };
  const running = Boolean(activeQueryId && (!query || !terminal.has(query.status)));

  return <div className="space-y-6">
    {loadingConnections ? <p role="status">Loading connections...</p> : connectionsError ? (
      <p role="alert" className="text-red-700">{connectionsError}</p>
    ) : connections.length ? (
      <QuestionForm connections={connections} selectedConnectionId={connectionId} onSelectConnection={setConnectionId}
        onQuerySubmitted={submitted} disabled={running} />
    ) : <div className="rounded-lg border bg-white p-6">
      <p>Connect a database and select its allowed tables to start asking questions.</p>
      <button onClick={onNavigateToConnections} className="mt-3 text-indigo-700 underline">Add database connection</button>
    </div>}
    {pollError && <div role="alert" className="rounded border border-red-200 bg-red-50 p-4">
      {pollError} <button onClick={() => setRetry((value) => value + 1)} className="underline">Retry now</button>
      {running && <button onClick={() => { setActiveQueryId(null); onActiveQueryChange?.(null); setQuery(null); }} className="ml-4 underline">Dismiss view</button>}
    </div>}
    {query && <p className="font-semibold text-slate-800">{query.question}</p>}
    {activeQueryId && <QueryStatus status={cancelling ? 'cancelling' : query?.status || 'queued'} onCancel={() => void cancel()} />}
    {query?.status === 'clarification_required' && <Assumptions clarificationQuestion={query.clarification_question} />}
    {query && ['failed', 'rejected', 'interrupted', 'cancelled'].includes(query.status) && 'safe_message' in query && (
      <p role="alert" className="rounded border bg-white p-4">{query.safe_message}</p>
    )}
    {query?.status === 'completed' && <>
      <SQLPanel sql={query.sql} dialect={query.dialect} />
      <Assumptions assumptions={query.assumptions} warnings={query.warnings} resultsExpired={!query.results_available} />
      {query.results_available && query.rows ? <>
        <ResultsTable columns={query.columns} rows={query.rows} truncated={query.truncated} />
        <a className="text-indigo-700 underline" href={`/api/v1/queries/${query.query_id}/export?format=csv`}>Download CSV</a>
      </> : <p>Results have expired or the connection policy changed. Submit the question again to retrieve fresh results.</p>}
    </>}
    {trace && <div>
      <button onClick={() => setInspecting((value) => !value)} className="text-indigo-700 underline">{inspecting ? 'Hide diagnostics' : 'Show diagnostics'}</button>
      {inspecting && <QueryInspector trace={trace} status={query?.status || trace.status} />}
    </div>}
  </div>;
}

export default WorkspaceView;
