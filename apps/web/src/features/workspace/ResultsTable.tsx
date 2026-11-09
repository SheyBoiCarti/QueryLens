import React from 'react';
import { ColumnMeta } from '../../api/generated/schema.ts';

interface ResultsTableProps {
  columns: ColumnMeta[];
  rows: Record<string, string | number | boolean | null>[];
  truncated?: boolean;
}

export function ResultsTable({ columns, rows, truncated = false }: ResultsTableProps): React.JSX.Element {
  if (rows.length === 0) {
    return (
      <div className="bg-surface rounded-lg border border-border p-8 text-center text-muted">
        Query completed with 0 rows returned.
      </div>
    );
  }

  return (
    <div className="overflow-hidden">
      {truncated && (
        <div className="bg-subtle border-b border-border px-4 py-2 text-xs text-muted font-medium">
          Result set was truncated at requested row limit. Additional matching rows exist.
        </div>
      )}

      <div className="overflow-x-auto max-h-[500px]" tabIndex={0} role="region" aria-label="Query result rows">
        <table className="min-w-full divide-y divide-border text-left text-sm">
          <thead className="bg-subtle sticky top-0 z-10">
            <tr>
              {columns.map((col) => (
                <th scope="col" key={col.name} className="font-medium">
                  <div className="flex items-center space-x-1">
                    <span className="font-mono text-xs">{col.name}</span>
                    <span className="badge type-tag">
                      {col.type}
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border font-mono text-xs">
            {rows.map((row, rIdx) => (
              <tr key={rIdx} className="hover:bg-subtle">
                {columns.map((col) => {
                  const val = row[col.name];
                  return (
                    <td key={col.name} className="whitespace-nowrap text-text">
                      {val === null ? (
                        <span className="text-dim italic">null</span>
                      ) : (
                        String(val)
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="table-card-footer">
        <span>Showing {rows.length} rows</span>
        <span>Results are temporarily cached</span>
      </div>
    </div>
  );
}

export default ResultsTable;
