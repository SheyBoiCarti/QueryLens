import React from 'react';
import { api } from '../../api/client.ts';

interface QueryStatusProps {
  status: string;
  onCancel?: () => void;
}

export function QueryStatus({ status, onCancel }: QueryStatusProps): React.JSX.Element {
  const isRunning = ['queued', 'contextualizing', 'generating', 'validating', 'executing', 'repairing'].includes(status);

  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4 flex items-center justify-between">
      <div className="flex items-center space-x-3">
        {isRunning && (
          <div className="w-4 h-4 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
        )}
        <div>
          <span className="text-sm font-semibold text-slate-900 capitalize">{status}</span>
          <p className="text-xs text-slate-500">
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
          className="px-3 py-1 border border-slate-300 rounded text-xs text-slate-600 hover:bg-slate-50"
        >
          Cancel
        </button>
      )}
    </div>
  );
}

export default QueryStatus;
