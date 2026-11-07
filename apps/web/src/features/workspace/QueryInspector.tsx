import React, { useState } from 'react';

export interface AttemptTrace {
  attempt_number: number;
  status: string;
  generated_sql?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  error_signature?: string | null;
}

export interface TraceData {
  query_id: string;
  status: string;
  attempts: AttemptTrace[];
}

export interface QueryInspectorProps {
  trace: TraceData;
  status: string;
  onCancel?: () => void;
  isCancelling?: boolean;
}

export function QueryInspector({
  trace,
  status,
  onCancel,
  isCancelling = false,
}: QueryInspectorProps): React.JSX.Element {
  const [expandedAttempts, setExpandedAttempts] = useState<Record<number, boolean>>({});

  const toggleAttempt = (num: number) => {
    setExpandedAttempts((prev) => ({
      ...prev,
      [num]: !prev[num],
    }));
  };

  const isRunning = [
    'queued',
    'contextualizing',
    'generating',
    'validating',
    'executing',
    'repairing',
  ].includes(status);

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-5 space-y-4" data-testid="query-inspector">
      {/* Header and Status */}
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Query Inspector & Diagnostics</h3>
          <p className="text-xs text-slate-500 font-mono">Run ID: {trace.query_id}</p>
        </div>

        <div className="flex items-center space-x-3">
          <span
            className={`px-2.5 py-1 rounded-full text-xs font-medium uppercase tracking-wide ${
              status === 'completed'
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                : status === 'cancelling'
                ? 'bg-amber-50 text-amber-700 border border-amber-200 animate-pulse'
                : status === 'cancelled'
                ? 'bg-slate-100 text-slate-700 border border-slate-200'
                : status === 'rejected' || status === 'failed'
                ? 'bg-rose-50 text-rose-700 border border-rose-200'
                : 'bg-indigo-50 text-indigo-700 border border-indigo-200'
            }`}
            data-testid="status-badge"
          >
            {status === 'cancelling' ? 'Cancelling...' : status}
          </span>

          {isRunning && onCancel && (
            <button
              onClick={onCancel}
              disabled={isCancelling || status === 'cancelling'}
              className="px-3 py-1.5 bg-rose-600 text-white rounded text-xs font-medium hover:bg-rose-700 disabled:opacity-50 transition-colors focus:ring-2 focus:ring-rose-500 focus:outline-none"
              aria-label="Cancel query execution"
            >
              {isCancelling || status === 'cancelling' ? 'Cancelling...' : 'Cancel Query'}
            </button>
          )}
        </div>
      </div>

      {/* Accuracy Warning */}
      <div className="bg-slate-50 border-l-4 border-slate-400 p-3 text-xs text-slate-600">
        AI-generated SQL queries are bounded to read-only semantics. Verify analytical assumptions before making critical business decisions.
      </div>

      {/* Attempts Timeline */}
      <div className="space-y-3">
        <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
          Execution Attempts ({trace.attempts.length})
        </h4>

        {trace.attempts.length === 0 ? (
          <p className="text-xs text-slate-400 italic">No execution attempts recorded yet.</p>
        ) : (
          <div className="space-y-2">
            {trace.attempts.map((att) => {
              const isExpanded = expandedAttempts[att.attempt_number] ?? true;
              const isRepair = att.attempt_number > 1;

              return (
                <div
                  key={att.attempt_number}
                  className="border border-slate-200 rounded-md p-3 text-sm bg-white hover:border-slate-300 transition-colors"
                  data-testid={`attempt-${att.attempt_number}`}
                >
                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => toggleAttempt(att.attempt_number)}
                      className="flex items-center space-x-2 text-left font-medium text-slate-800 focus:outline-none"
                      aria-expanded={isExpanded}
                    >
                      <span>
                        Attempt {att.attempt_number} {isRepair ? '(Repair)' : '(Initial Generation)'}
                      </span>
                    </button>

                    <div className="flex items-center space-x-2 text-xs text-slate-500">
                      <span>{att.latency_ms}ms</span>
                      <span>•</span>
                      <span>{att.prompt_tokens + att.completion_tokens} tokens</span>
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${
                          att.status === 'success' || att.status === 'completed'
                            ? 'bg-emerald-100 text-emerald-800'
                            : att.status === 'failed'
                            ? 'bg-rose-100 text-rose-800'
                            : 'bg-slate-100 text-slate-700'
                        }`}
                      >
                        {att.status}
                      </span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="mt-2.5 pt-2 border-t border-slate-100 space-y-2 text-xs">
                      {att.error_signature && (
                        <div className="text-rose-600 font-mono bg-rose-50 p-2 rounded">
                          Repair Reason: {att.error_signature}
                        </div>
                      )}

                      {att.generated_sql && (
                        <div>
                          <div className="text-slate-500 font-medium mb-1">Generated SQL:</div>
                          <pre className="p-2 bg-slate-900 text-slate-100 rounded font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                            {att.generated_sql}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default QueryInspector;
