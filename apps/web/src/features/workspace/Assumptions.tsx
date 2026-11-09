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
          className="bg-subtle border border-border text-muted text-xs p-3 rounded-md font-medium"
        >
          Cached query results have expired (300s TTL). SQL query and attempt diagnostics remain preserved for audit.
        </div>
      )}

      {clarificationQuestion && (
        <div className="bg-subtle border border-border-control text-accent text-sm p-4 rounded-md">
          <span className="font-semibold block mb-1">Clarification required:</span>
          <p className="text-xs text-accent">{clarificationQuestion}</p>
        </div>
      )}

      {assumptions.length > 0 && (
        <div className="bg-subtle border border-border rounded-md p-3 text-xs">
          <span className="font-semibold text-text block mb-1">Model assumptions:</span>
          <ul className="list-disc list-inside space-y-1 text-muted">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="bg-surface border border-danger-border rounded-md p-3 text-xs">
          <span className="font-semibold text-danger block mb-1">Semantic warnings:</span>
          <ul className="list-disc list-inside space-y-1 text-danger">
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
