import React from 'react';

interface QueryStatusProps {
  status: string;
  question?: string;
  onCancel?: () => void;
}

export function QueryStatus({ status, question, onCancel }: QueryStatusProps): React.JSX.Element {
  const isRunning = ['queued', 'contextualizing', 'generating', 'validating', 'executing', 'repairing'].includes(status);

  return (
    <div className="card space-y-3" role="status">
      {question && <p className="font-medium">{question}</p>}
      <div className="flex items-center justify-between gap-4">
      <div className="flex items-center space-x-3">
        {isRunning && (
          <div className="w-4 h-4 border-2 border-border-control border-t-transparent rounded-full animate-spin" aria-hidden="true" />
        )}
        <div className="flex flex-wrap items-center gap-3">
          <span className={`badge ${status === 'completed' ? 'badge-success' : ['failed', 'rejected'].includes(status) ? 'badge-danger' : ''}`}>{status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, ' ')}</span>
          <p className="text-xs text-muted">
            {status === 'queued' && 'Query queued for pipeline execution...'}
            {status === 'contextualizing' && 'Assembling authorized schema context...'}
            {status === 'generating' && 'Synthesizing SQL with structured model...'}
            {status === 'validating' && 'Verifying AST security policies and limits...'}
            {status === 'executing' && 'Executing read-only statement on source engine...'}
            {status === 'completed' && 'Execution completed successfully.'}
            {status === 'clarification_required' && 'Additional clarification needed from user.'}
            {status === 'rejected' && 'Query rejected by security or AST policy.'}
            {status === 'failed' && 'Query pipeline failed.'}
            {status === 'cancelled' && 'Query was cancelled.'}
          </p>
        </div>
      </div>

      {isRunning && onCancel && (
        <button
          onClick={onCancel}
          className="border rounded text-muted"
        >
          Cancel
        </button>
      )}
      </div>
    </div>
  );
}

export default QueryStatus;
