import React, { useState, useEffect } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';
import { QuestionForm } from './QuestionForm.tsx';
import { QueryStatus } from './QueryStatus.tsx';
import { ResultsTable } from './ResultsTable.tsx';
import { SQLPanel } from './SQLPanel.tsx';
import { Assumptions } from './Assumptions.tsx';
import { QueryInspector, TraceData } from './QueryInspector.tsx';

interface WorkspaceViewProps {
  onNavigateToConnections: () => void;
}

export function WorkspaceView({ onNavigateToConnections }: WorkspaceViewProps): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string>('');
  const [loadingConnections, setLoadingConnections] = useState(true);
  const [connectionsError, setConnectionsError] = useState<string | null>(null);

  // In-flight / Completed Query state
  const [activeQueryId, setActiveQueryId] = useState<string | null>(null);
  const [queryState, setQueryState] = useState<any | null>(null);
  const [traceData, setTraceData] = useState<TraceData | null>(null);
  const [showInspector, setShowInspector] = useState(false);

  const loadConnections = () => {
    setLoadingConnections(true);
    setConnectionsError(null);
    api.get<ConnectionResponse[]>('/api/v1/connections')
      .then((conns) => {
        setConnections(conns);
        if (conns.length > 0) {
          setSelectedConnectionId(conns[0].id);
        }
      })
      .catch((err) => {
        setConnectionsError(err instanceof ApiError ? err.message : 'Could not fetch database connections');
      })
      .finally(() => {
        setLoadingConnections(false);
      });
  };

  useEffect(() => {
    loadConnections();
  }, []);

  // Poll active query state until terminal
  useEffect(() => {
    if (!activeQueryId) return;

    let isMounted = true;
    const interval = setInterval(async () => {
      try {
        const run = await api.get<any>(`/api/v1/queries/${activeQueryId}`);
        if (!isMounted) return;
        setQueryState(run);

        const terminalStates = ['completed', 'failed', 'rejected', 'clarification_required', 'cancelled', 'interrupted'];
        if (terminalStates.includes(run.status)) {
          clearInterval(interval);
          // Fetch trace
          try {
            const trace = await api.get<TraceData>(`/api/v1/queries/${activeQueryId}/trace`);
            if (isMounted) setTraceData(trace);
          } catch {
            // Ignore trace fetch failure
          }
        }
      } catch (err) {
        if (isMounted) {
          clearInterval(interval);
        }
      }
    }, 1000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [activeQueryId]);

  const handleCancel = async () => {
    if (!activeQueryId) return;
    try {
      await api.post(`/api/v1/queries/${activeQueryId}/cancel`);
    } catch {
      // Ignore cancel error
    }
  };

  const handleQuerySubmitted = (queryId: string) => {
    setActiveQueryId(queryId);
    setQueryState({ status: 'queued' });
    setTraceData(null);
    setShowInspector(false);
  };

  if (loadingConnections) {
    return (
      <div className="bg-white rounded-lg border border-slate-200 p-8 text-center text-slate-500">
        Loading database connections...
      </div>
    );
  }

  if (connectionsError && connections.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-red-200 p-8 text-center space-y-4">
        <div className="text-red-700 text-sm font-medium">{connectionsError}</div>
        <button
          onClick={loadConnections}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm rounded-md shadow-sm transition"
        >
          Retry Loading Connections
        </button>
      </div>
    );
  }

  if (connections.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-dashed border-slate-300 p-12 text-center space-y-4">
        <div className="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center mx-auto text-xl font-bold">
          !
        </div>
        <div>
          <h3 className="text-lg font-semibold text-slate-900">No Database Connected</h3>
          <p className="text-sm text-slate-500 max-w-md mx-auto mt-1">
            To ask natural language questions, connect a PostgreSQL or MySQL analytics database first.
          </p>
        </div>
        <button
          onClick={onNavigateToConnections}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm rounded-md shadow-sm transition"
        >
          Add Database Connection
        </button>
      </div>
    );
  }

  const selectedConn = connections.find((c) => c.id === selectedConnectionId);

  return (
    <div className="space-y-6">
      <QuestionForm
        connections={connections}
        selectedConnectionId={selectedConnectionId}
        onSelectConnection={setSelectedConnectionId}
        onQuerySubmitted={handleQuerySubmitted}
        disabled={queryState && ['queued', 'contextualizing', 'generating', 'validating', 'executing', 'repairing'].includes(queryState.status)}
      />

      {queryState && (
        <div className="space-y-6">
          <QueryStatus status={queryState.status} onCancel={handleCancel} />

          {queryState.status === 'clarification_required' && (
            <Assumptions
              clarificationQuestion={
                queryState.clarification_question?.trim() ||
                'The question is ambiguous (for example: did you mean the highest total count of orders, or the highest total monetary spend across orders?). Please rephrase or specify in the input above.'
              }
              assumptions={queryState.assumptions || []}
            />
          )}

          {queryState.status === 'rejected' && (
            <div className="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-lg text-sm">
              <span className="font-semibold">Query Rejected by Policy:</span> {queryState.safe_message || 'Policy violation.'}
            </div>
          )}

          {queryState.status === 'failed' && (
            <div className="bg-red-50 border border-red-200 text-red-800 p-4 rounded-lg text-sm">
              <span className="font-semibold">Pipeline Error:</span> {queryState.safe_message || 'Execution error.'}
            </div>
          )}

          {queryState.sql && (
            <SQLPanel sql={queryState.sql} dialect={selectedConn?.engine || 'postgresql'} />
          )}

          {queryState.assumptions && queryState.assumptions.length > 0 && queryState.status === 'completed' && (
            <Assumptions
              assumptions={queryState.assumptions}
              warnings={queryState.warnings || []}
              resultsExpired={!queryState.results_available}
            />
          )}

          {queryState.status === 'completed' && queryState.columns && queryState.rows && (
            <ResultsTable
              columns={queryState.columns}
              rows={queryState.rows}
              truncated={queryState.truncated}
            />
          )}

          {traceData && (
            <div className="pt-2">
              <button
                onClick={() => setShowInspector(!showInspector)}
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 underline focus:outline-none"
              >
                {showInspector ? 'Hide Diagnostics & Attempt Trace' : 'Show Diagnostics & Attempt Trace'}
              </button>
              {showInspector && (
                <div className="mt-4">
                  <QueryInspector trace={traceData} status={queryState.status} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default WorkspaceView;
