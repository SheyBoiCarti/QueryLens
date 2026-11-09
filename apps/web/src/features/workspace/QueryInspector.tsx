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
    <div className="bg-surface rounded-lg border border-border p-5 space-y-4" data-testid="query-inspector">
      {/* Header and Status */}
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div>
          <h3 className="text-base font-semibold text-text">Query inspector & diagnostics</h3>
          <p className="text-xs text-muted font-mono">Run ID: {trace.query_id}</p>
        </div>

        <div className="flex items-center space-x-3">
          <span
            className={`px-2.5 py-1 rounded-full text-xs font-medium   ${
              status === 'completed'
                ? 'bg-accent-bg text-accent border border-accent-border'
                : status === 'cancelling'
                ? 'bg-subtle text-muted border border-border animate-pulse'
                : status === 'cancelled'
                ? 'bg-subtle text-text border border-border'
                : status === 'rejected' || status === 'failed'
                ? 'bg-surface text-danger border border-danger-border'
                : 'bg-subtle text-accent border border-border-control'
            }`}
            data-testid="status-badge"
          >
            {status === 'cancelling' ? 'Cancelling...' : status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ')}
          </span>

          {isRunning && onCancel && (
            <button
              onClick={onCancel}
              disabled={isCancelling || status === 'cancelling'}
              className="text-white rounded font-medium hover:bg-surface transition-colors"
              aria-label="Cancel query execution"
            >
              {isCancelling || status === 'cancelling' ? 'Cancelling...' : 'Cancel query'}
            </button>
          )}
        </div>
      </div>

      {/* Accuracy Warning */}
      <div className="bg-subtle border border-border p-3 text-xs text-muted">
        AI-generated SQL queries are bounded to read-only semantics. Verify analytical assumptions before making critical business decisions.
      </div>

      {/* Attempts Timeline */}
      <div className="space-y-3">
        <h4 className="text-xs font-semibold text-text">
          Execution attempts ({trace.attempts.length})
        </h4>

        {trace.attempts.length === 0 ? (
          <p className="text-xs text-dim italic">No execution attempts recorded yet.</p>
        ) : (
          <div className="space-y-2">
            {trace.attempts.map((att) => {
              const isExpanded = expandedAttempts[att.attempt_number] ?? true;
              const isRepair = att.attempt_number > 1;

              return (
                <div
                  key={att.attempt_number}
                  className="border border-border rounded-md p-3 text-sm bg-surface hover:border-border transition-colors"
                  data-testid={`attempt-${att.attempt_number}`}
                >
                  <div className="flex items-center justify-between">
                    <button
                      onClick={() => toggleAttempt(att.attempt_number)}
                      className="flex items-center space-x-2 text-left font-medium text-text"
                      aria-expanded={isExpanded}
                    >
                      <span>
                        Attempt {att.attempt_number} {isRepair ? '(Repair)' : '(Initial Generation)'}
                      </span>
                    </button>

                    <div className="flex items-center space-x-2 text-xs text-muted">
                      <span>{att.latency_ms}ms</span>
                      <span>•</span>
                      <span>{att.prompt_tokens + att.completion_tokens} tokens</span>
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${
                          att.status === 'success' || att.status === 'completed'
                            ? 'bg-accent-bg text-accent'
                            : att.status === 'failed'
                            ? 'bg-surface text-danger'
                            : 'bg-subtle text-text'
                        }`}
                      >
                        {att.status.charAt(0).toUpperCase() + att.status.slice(1).replace(/_/g, ' ')}
                      </span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="mt-2.5 pt-2 border-t border-border space-y-2 text-xs">
                      {att.error_signature && (
                        <div className="text-danger font-mono bg-surface p-2 rounded">
                          Repair reason: {att.error_signature}
                        </div>
                      )}

                      {att.generated_sql && (
                        <div>
                          <div className="text-muted font-medium mb-1">Generated SQL:</div>
                          <pre className="p-2 bg-surface text-text rounded font-mono text-xs overflow-x-auto whitespace-pre-wrap">
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
