import React from 'react';

export interface AssumptionsProps {
  assumptions?: string[];
  warnings?: string[];
  clarificationQuestion?: string | null;
  resultsExpired?: boolean;
}

export function Assumptions({
  assumptions = [],
  warnings = [],
  clarificationQuestion = null,
  resultsExpired = false,
}: AssumptionsProps): React.JSX.Element {
  return (
    <div className="space-y-3" data-testid="assumptions-panel">
      {resultsExpired && (
        <div
          role="status"
          className="bg-amber-50 border border-amber-200 text-amber-800 text-xs p-3 rounded-md font-medium"
        >
          Cached query results have expired (300s TTL). SQL query and attempt diagnostics remain preserved for audit.
        </div>
      )}

      {clarificationQuestion && (
        <div className="bg-indigo-50 border border-indigo-200 text-indigo-900 text-sm p-4 rounded-md">
          <span className="font-semibold block mb-1">Clarification Required:</span>
          <p className="text-xs text-indigo-700">{clarificationQuestion}</p>
        </div>
      )}

      {assumptions.length > 0 && (
        <div className="bg-slate-50 border border-slate-200 rounded-md p-3 text-xs">
          <span className="font-semibold text-slate-700 block mb-1">Model Assumptions:</span>
          <ul className="list-disc list-inside space-y-1 text-slate-600">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="bg-rose-50 border border-rose-200 rounded-md p-3 text-xs">
          <span className="font-semibold text-rose-800 block mb-1">Semantic Warnings:</span>
          <ul className="list-disc list-inside space-y-1 text-rose-700">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default Assumptions;
