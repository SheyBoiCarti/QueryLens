import React, { useEffect, useState, useRef } from 'react';
import { useDatabaseBreadcrumb } from '../../components/AppShell.tsx';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionResponse, PublicRun, PublicRunCompleted } from '../../api/generated/schema.ts';
import { QuestionForm } from './QuestionForm.tsx';
import { QueryStatus } from './QueryStatus.tsx';
import { AnswerPresentation } from './AnswerPresentation.tsx';
import { Assumptions } from './Assumptions.tsx';
import { QueryInspector, TraceData } from './QueryInspector.tsx';
import { SavedQuestionsModal } from './SavedQuestionsModal.tsx';
import { SavedQuestionsManager } from './SavedQuestionsManager.tsx';
import { FollowUpBar } from './FollowUpBar.tsx';

interface WorkspaceViewProps {
  onNavigateToConnections: () => void;
  initialQueryId?: string | null;
  onActiveQueryChange?: (id: string | null) => void;
}

const terminal = new Set(['completed', 'failed', 'rejected', 'clarification_required', 'cancelled', 'interrupted']);

export function WorkspaceView({
  onNavigateToConnections,
  initialQueryId,
  onActiveQueryChange,
}: WorkspaceViewProps): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [connectionId, setConnectionId] = useState('');
  const [connectionsError, setConnectionsError] = useState<string | null>(null);
  const [loadingConnections, setLoadingConnections] = useState(true);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialQueryId || null);
  const [inFlightRunId, setInFlightRunId] = useState<string | null>(null);
  const [lastSuccessfulRunId, setLastSuccessfulRunId] = useState<string | null>(null);
  const [loadedRuns, setLoadedRuns] = useState<Record<string, PublicRun>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const [inspecting, setInspecting] = useState(false);
  const [trace, setTrace] = useState<TraceData | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [followUpError, setFollowUpError] = useState<{ message: string; code?: string; question: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [showSavedManager, setShowSavedManager] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);

  const activeConnection = connections.find((item) => item.id === connectionId);
  useDatabaseBreadcrumb(activeConnection?.database, Object.keys(activeConnection?.allowed_tables ?? {})[0]?.split('.')[0]);

  // Track draft state for confirmation checks
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;
  const loadedRunsRef = useRef(loadedRuns);
  loadedRunsRef.current = loadedRuns;

  useEffect(() => {
    const now = Date.now();
    const expiredIds = Object.values(loadedRuns).flatMap((run) =>
      run.status === 'completed' && run.results_available && run.results_expires_at
        && new Date(run.results_expires_at).getTime() <= now ? [run.query_id] : []
    );
    if (expiredIds.length) {
      setLoadedRuns((previous) => {
        const next = { ...previous };
        for (const id of expiredIds) {
          const run = next[id];
          if (run?.status === 'completed') next[id] = { ...run, results_available: false, rows: undefined, presentation: undefined };
        }
        return next;
      });
    }
    const nextExpiry = Object.values(loadedRuns)
      .flatMap((run) => run.status === 'completed' && run.results_available && run.results_expires_at
        ? [new Date(run.results_expires_at).getTime()] : [])
      .filter((expiry) => expiry > now)
      .sort((left, right) => left - right)[0];
    if (!nextExpiry) return;
    const timer = window.setTimeout(() => {
      setLoadedRuns((previous) => {
        const next = { ...previous };
        for (const [id, run] of Object.entries(next)) {
          if (run.status === 'completed' && run.results_available && run.results_expires_at
              && new Date(run.results_expires_at).getTime() <= Date.now()) {
            next[id] = { ...run, results_available: false, rows: undefined, presentation: undefined };
          }
        }
        return next;
      });
    }, Math.max(0, nextExpiry - now));
    return () => window.clearTimeout(timer);
  }, [loadedRuns]);

  const isDraftDirty = (runId: string | null): boolean => {
    if (!runId) return false;
    const draft = draftsRef.current[runId];
    const run = loadedRunsRef.current[runId];
    if (draft !== undefined && run && run.status === 'completed' && 'sql' in run) {
      return draft !== run.sql;
    }
    return false;
  };

  const confirmDiscardIfDirty = (callback: () => void) => {
    if (isDraftDirty(selectedRunId)) {
      if (!window.confirm('You have unsaved SQL edits. Discard changes?')) {
        return;
      }
    }
    callback();
  };

  useEffect(() => {
    const abort = new AbortController();
    api.get<ConnectionResponse[]>('/api/v1/connections', { signal: abort.signal })
      .then((items) => {
        if (abort.signal.aborted) return;
        setConnections(items);
        setConnectionId((prev) => items.some((item) => item.id === prev) ? prev : items[0]?.id || '');
      })
      .catch((err: unknown) => {
        if (!abort.signal.aborted) {
          setConnectionsError(err instanceof Error ? err.message : 'Could not load connections');
        }
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoadingConnections(false);
      });
    return () => abort.abort();
  }, []);

  // Update selectedRunId if initialQueryId changes from parent
  useEffect(() => {
    if (initialQueryId && initialQueryId !== selectedRunId) {
      confirmDiscardIfDirty(() => {
        setSelectedRunId(initialQueryId);
      });
    }
  }, [initialQueryId]);

  // Polling effect for active target (inFlightRunId or selectedRunId)
  const targetId = inFlightRunId || selectedRunId;

  useEffect(() => {
    if (!targetId) return;
    const abort = new AbortController();
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let expiryTimer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;

    const poll = async () => {
      try {
        const run = await api.get<PublicRun>(`/api/v1/queries/${targetId}`, { signal: abort.signal });
        if (abort.signal.aborted) return;

        setConnectionId(run.connection_id);
        setLoadedRuns((previous) => {
          const prev = previous[targetId];
          if (!prev) return { ...previous, [targetId]: run };
          // Availability changes must NOT be discarded by state_version comparison
          if (prev.state_version > run.state_version) {
            if ('results_available' in run && 'results_available' in prev && run.results_available !== prev.results_available) {
              return { ...previous, [targetId]: run };
            }
            return previous;
          }
          return { ...previous, [targetId]: run };
        });

        if (run.status === 'completed' && run.results_available) {
          setLastSuccessfulRunId(run.query_id);
        }
        if (terminal.has(run.status) && inFlightRunId === targetId) {
          setSelectedRunId(targetId);
          setInFlightRunId(null);
        }

        setPollError(null);
        failures = 0;

        if (terminal.has(run.status)) {
          setCancelling(false);
          try {
            const data = await api.get<TraceData>(`/api/v1/queries/${targetId}/trace`, { signal: abort.signal });
            if (!abort.signal.aborted) setTrace(data);
          } catch {
            /* Results remain usable when diagnostics are unavailable */
          }

          // If completed with valid rows and results_expires_at, set expiry timer
          if (run.status === 'completed' && run.results_available && run.results_expires_at) {
            const remainingMs = new Date(run.results_expires_at).getTime() - Date.now();
            if (remainingMs > 0) {
              if (expiryTimer) clearTimeout(expiryTimer);
              expiryTimer = setTimeout(() => {
                if (abort.signal.aborted) return;
                setLoadedRuns((prev) => {
                  const current = prev[targetId];
                  if (current && current.status === 'completed') {
                    return { ...prev, [targetId]: { ...current, results_available: false, rows: undefined, presentation: undefined } };
                  }
                  return prev;
                });
                void poll();
              }, remainingMs);
            } else {
              setLoadedRuns((prev) => {
                const current = prev[targetId];
                if (current && current.status === 'completed') {
                  return { ...prev, [targetId]: { ...current, results_available: false, rows: undefined, presentation: undefined } };
                }
                return prev;
              });
            }
          }
          return;
        }
      } catch (err) {
        if (abort.signal.aborted) return;
        failures += 1;
        setPollError(err instanceof Error ? err.message : 'Could not refresh query status');
        if (err instanceof ApiError && [401, 403, 404].includes(err.statusCode)) {
          // Clear protected data on authorization failure / revocation
          setLoadedRuns((prev) => {
            const updated = { ...prev };
            if (updated[targetId]) {
              delete updated[targetId];
            }
            return updated;
          });
          setSelectedRunId(null);
          setInFlightRunId(null);
          setTrace(null);
          setInspecting(false);
          setCancelling(false);
          onActiveQueryChange?.(null);
          setPollError(err.statusCode === 404
            ? 'This query is no longer available. Select a database to start a new question.'
            : err.message);
          return;
        }
      }
      if (!abort.signal.aborted) {
        pollTimer = setTimeout(() => void poll(), Math.min(30000, 1000 * 2 ** failures));
      }
    };

    void poll();

    // Revalidate completed runs on focus and periodic refresh (every 30s)
    let lastRevalidate = Date.now();
    const handleFocus = () => {
      const now = Date.now();
      if (now - lastRevalidate >= 30000) {
        lastRevalidate = now;
        void poll();
      }
    };
    window.addEventListener('focus', handleFocus);

    const revalidateInterval = setInterval(() => {
      if (!abort.signal.aborted) {
        lastRevalidate = Date.now();
        void poll();
      }
    }, 30000);

    return () => {
      abort.abort();
      if (pollTimer) clearTimeout(pollTimer);
      if (expiryTimer) clearTimeout(expiryTimer);
      clearInterval(revalidateInterval);
      window.removeEventListener('focus', handleFocus);
    };
  }, [targetId, retry]);

  const submitted = (id: string) => {
    setInFlightRunId(id);
    setSelectedRunId(id);
    onActiveQueryChange?.(id);
    setTrace(null);
    setInspecting(false);
    setPollError(null);
  };

  const handleRunSql = async (draft: string) => {
    if (!selectedRunId) return;
    const currentRun = loadedRuns[selectedRunId];
    const conn = connectionId || (currentRun ? currentRun.connection_id : '');
    try {
      const res = await api.post<{ query_id: string; status: string }>('/api/v1/queries/sql', {
        connection_id: conn,
        sql: draft,
        source_query_id: selectedRunId,
        max_rows: 100,
      });
      submitted(res.query_id);
    } catch (err) {
      setPollError(err instanceof Error ? err.message : 'Failed to execute edited SQL');
    }
  };

  const cancel = async () => {
    const idToCancel = inFlightRunId || selectedRunId;
    if (!idToCancel) return;
    setCancelling(true);
    try {
      await api.post(`/api/v1/queries/${idToCancel}/cancel`);
      setRetry((value) => value + 1);
    } catch (err) {
      setPollError(err instanceof Error ? err.message : 'Cancellation failed; please retry');
      setCancelling(false);
    }
  };

  const handleFollowUpSubmit = async (question: string, parentQueryId: string) => {
    setFollowUpError(null);
    try {
      const res = await api.post<{ query_id: string; status: string }>('/api/v1/queries', {
        connection_id: connectionId,
        question,
        parent_query_id: parentQueryId,
        max_rows: 100,
      });
      submitted(res.query_id);
    } catch (err) {
      if (err instanceof ApiError && (err.statusCode === 409 || err.code === 'FOLLOWUP_CONTEXT_STALE' || err.code === 'FOLLOWUP_CONTEXT_OVERSIZED')) {
        setFollowUpError({
          message: err.message,
          code: err.code,
          question,
        });
      } else {
        setPollError(err instanceof Error ? err.message : 'Failed to submit follow-up query');
      }
      throw err;
    }
  };

  const handleAskStandalone = async (question: string) => {
    setFollowUpError(null);
    try {
      const res = await api.post<{ query_id: string; status: string }>('/api/v1/queries', {
        connection_id: connectionId,
        question,
        max_rows: 100,
      });
      submitted(res.query_id);
    } catch (err) {
      setPollError(err instanceof Error ? err.message : 'Failed to submit standalone query');
    }
  };

  const handleStartNewQuestion = () => {
    confirmDiscardIfDirty(() => {
      setSelectedRunId(null);
      setInFlightRunId(null);
      onActiveQueryChange?.(null);
      setFollowUpError(null);
      setPollError(null);
      setTrace(null);
      setInspecting(false);
      setShowSaveModal(false);
    });
  };

  async function handleRerun(run: PublicRunCompleted): Promise<void> {
    const resolved = run.context?.resolved_parameters;
    const maxRows = resolved?.max_rows ?? run.max_rows ?? 100;
    const savedQuestion = run.origin === 'saved_question' && run.saved_question_id;

    try {
      let response: { query_id: string };
      if (savedQuestion) {
        response = await api.post(`/api/v1/saved-questions/${run.saved_question_id}/run`, {
          parameters: resolved?.values ?? {},
          expected_revision: run.saved_question_version,
        });
      } else if (run.origin === 'manual_sql' && run.sql) {
        response = await api.post('/api/v1/queries/sql', {
          connection_id: run.connection_id,
          sql: run.sql,
          source_query_id: run.query_id,
          max_rows: maxRows,
        });
      } else {
        response = await api.post('/api/v1/queries', {
          connection_id: run.connection_id,
          question: run.question,
          parent_query_id: run.origin === 'follow_up' ? run.parent_query_id : undefined,
          max_rows: maxRows,
        });
      }
      submitted(response.query_id);
    } catch {
      setPollError(savedQuestion ? 'Saved question rerun failed' : 'Rerun failed');
    }
  }

  const retainedRun = selectedRunId ? loadedRuns[selectedRunId] || null : null;
  const selectedRun = retainedRun?.status === 'completed' && retainedRun.results_expires_at
      && new Date(retainedRun.results_expires_at).getTime() <= Date.now()
    ? { ...retainedRun, results_available: false, rows: undefined, presentation: undefined }
    : retainedRun;
  const running = Boolean(inFlightRunId || (selectedRun && !terminal.has(selectedRun.status)));

  return (
    <div className="space-y-4">
      <div className="page-header">
        <div><h1 className="page-title">Ask data</h1><p className="page-subtitle">Ask a question, explore the results, and follow the data.</p></div>
        {!!connections.length && <button type="button" onClick={() => setShowSavedManager((value) => !value)}>
          {showSavedManager ? 'Hide saved questions' : 'Browse saved questions'}
        </button>}
      </div>
      {loadingConnections ? (
        <p role="status">Loading connections...</p>
      ) : connectionsError ? (
        <p role="alert" className="text-danger">{connectionsError}</p>
      ) : connections.length ? (
        <div className="space-y-3">

          {showSavedManager && (
            <SavedQuestionsManager
              connectionId={connectionId}
              onRunAccepted={(id) => {
                submitted(id);
                setShowSavedManager(false);
              }}
              onAskVariation={(question) => {
                setShowSavedManager(false);
                void handleAskStandalone(question);
              }}
              onClose={() => setShowSavedManager(false)}
            />
          )}

          <QuestionForm
            connections={connections}
            selectedConnectionId={connectionId}
            onSelectConnection={(newId) =>
              confirmDiscardIfDirty(() => {
                setConnectionId(newId);
                setSelectedRunId(null);
                setInFlightRunId(null);
                onActiveQueryChange?.(null);
                setLoadedRuns({});
                setDrafts({});
                setLastSuccessfulRunId(null);
                setTrace(null);
                setInspecting(false);
                setPollError(null);
                setFollowUpError(null);
                setShowSaveModal(false);
              })
            }
            onQuerySubmitted={submitted}
            disabled={running}
          />
        </div>
      ) : (
        <div className="rounded-lg border bg-surface p-6">
          <p>Connect a database and select its allowed tables to start asking questions.</p>
          <button onClick={onNavigateToConnections} className="mt-3 text-accent underline btn-link">
            Add database connection
          </button>
        </div>
      )}

      {pollError && (
        <div role="alert" className="rounded border border-danger-border bg-surface p-4">
          {pollError}{' '}
          <button onClick={() => setRetry((value) => value + 1)} className="underline">
            Retry now
          </button>
          {running && (
            <button
              onClick={() =>
                confirmDiscardIfDirty(() => {
                  setSelectedRunId(null);
                  setInFlightRunId(null);
                  onActiveQueryChange?.(null);
                })
              }
              className="ml-4 underline"
            >
              Dismiss view
            </button>
          )}
        </div>
      )}

      {followUpError && (
        <div role="alert" className="p-4 bg-subtle border border-border rounded-lg text-muted space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">{followUpError.message}</p>
            <button
              type="button"
              onClick={() => setFollowUpError(null)}
              className="text-muted hover:text-muted underline"
            >
              Dismiss
            </button>
          </div>
          <div className="flex items-center space-x-3 pt-1">
            <button
              type="button"
              onClick={() => handleAskStandalone(followUpError.question)}
              className="bg-subtle text-white rounded transition-colors"
            >
              Ask as a standalone question
            </button>
            <span className="text-xs text-muted">
              Starts a fresh question without inheriting previous context or schema assumptions.
            </span>
          </div>
        </div>
      )}

      {targetId && (
        <QueryStatus
          question={selectedRun?.question}
          status={cancelling ? 'cancelling' : selectedRun?.status || 'queued'}
          onCancel={() => void cancel()}
        />
      )}

      {selectedRun?.status === 'clarification_required' && (
        <Assumptions clarificationQuestion={selectedRun.clarification_question} />
      )}

      {selectedRun && ['failed', 'rejected', 'interrupted', 'cancelled'].includes(selectedRun.status) && 'safe_message' in selectedRun && (
        <div className="space-y-3">
          <p role="alert" className="rounded border bg-surface p-4">
            {selectedRun.safe_message}
          </p>

          {/* If manual execution failed, prior successful answer remains selectable */}
          {lastSuccessfulRunId && lastSuccessfulRunId !== selectedRunId && loadedRuns[lastSuccessfulRunId] && (
            <div className="p-3 bg-subtle border border-border rounded-md flex items-center justify-between">
              <span className="text-sm text-text">Prior successful query is available.</span>
              <button
                type="button"
                onClick={() => setSelectedRunId(lastSuccessfulRunId)}
                className="text-accent hover:text-accent font-medium underline btn-link"
              >
                View previous successful answer
              </button>
            </div>
          )}
        </div>
      )}

      {selectedRun?.status === 'completed' && (
        <div className="space-y-3">
          {showSaveModal && (
            <SavedQuestionsModal
              sourceQueryId={selectedRun.query_id}
              onClose={() => setShowSaveModal(false)}
            />
          )}

          <AnswerPresentation
            run={selectedRun}
            onSaveQuestion={() => setShowSaveModal(true)}
            draftValue={drafts[selectedRun.query_id]}
            onRunSql={handleRunSql}
            onDraftChange={(draft) => {
              setDrafts((prev) => ({ ...prev, [selectedRun.query_id]: draft }));
            }}
            disabled={running}
            onRerun={() => void handleRerun(selectedRun)}
          >
            <FollowUpBar
              parent={selectedRun}
              onSubmit={handleFollowUpSubmit}
              onStartNewQuestion={handleStartNewQuestion}
              disabled={running}
            />
          </AnswerPresentation>
        </div>
      )}

      {trace && (
        <details key={trace.query_id} className="disclosure" onToggle={(event) => setInspecting(event.currentTarget.open)}>
          <summary>Show diagnostics</summary>
          {inspecting && <QueryInspector trace={trace} status={selectedRun?.status || trace.status} />}
        </details>
      )}
    </div>
  );
}

export default WorkspaceView;
