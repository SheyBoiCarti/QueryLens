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
      <div className="bg-white rounded-lg border border-slate-200 p-8 text-center text-slate-500">
        Query completed with 0 rows returned.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-slate-200 overflow-hidden shadow-sm space-y-2">
      {truncated && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-xs text-amber-800 font-medium">
          Result set was truncated at requested row limit. Additional matching rows exist.
        </div>
      )}

      <div className="overflow-x-auto max-h-[500px]">
        <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
          <thead className="bg-slate-50 sticky top-0 z-10">
            <tr>
              {columns.map((col) => (
                <th key={col.name} className="py-2.5 px-4 font-semibold text-slate-700">
                  <div className="flex items-center space-x-1">
                    <span>{col.name}</span>
                    <span className="text-[10px] uppercase font-mono text-slate-400 font-normal">
                      {col.type}
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 font-mono text-xs">
            {rows.map((row, rIdx) => (
              <tr key={rIdx} className="hover:bg-slate-50">
                {columns.map((col) => {
                  const val = row[col.name];
                  return (
                    <td key={col.name} className="py-2 px-4 whitespace-nowrap text-slate-800">
                      {val === null ? (
                        <span className="text-slate-400 italic">null</span>
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

      <div className="p-3 bg-slate-50 border-t border-slate-200 text-xs text-slate-500 flex justify-between">
        <span>Showing {rows.length} rows</span>
        <span>Results are temporarily cached</span>
      </div>
    </div>
  );
}

export default ResultsTable;
