import React, { useState, useMemo } from 'react';
import { compareCell } from './resultComparators.ts';

export interface ColumnMeta {
  name: string;
  type: string;
  db_type?: string;
}

export interface DataGridProps {
  columns: ColumnMeta[];
  rows: Record<string, string | number | boolean | null>[];
  truncated?: boolean;
}

export function DataGrid({ columns, rows, truncated = false }: DataGridProps): React.JSX.Element {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const handleSort = (colName: string) => {
    if (sortCol === colName) {
      if (sortDir === 'asc') {
        setSortDir('desc');
      } else {
        setSortCol(null);
        setSortDir('asc');
      }
    } else {
      setSortCol(colName);
      setSortDir('asc');
    }
  };

  const sortedRows = useMemo(() => {
    if (!sortCol) return rows;
    const colMeta = columns.find((c) => c.name === sortCol);
    const colType = colMeta?.type || 'string';

    return [...rows].sort((a, b) => {
      const cmp = compareCell(a[sortCol], b[sortCol], colType);
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [rows, sortCol, sortDir, columns]);

  return (
    <div className="space-y-3" data-testid="data-grid">
      {truncated && (
        <div
          role="alert"
          className="bg-subtle border border-border text-muted text-xs px-3 py-2 rounded-md font-medium"
        >
          Result set was truncated at server limit (showing first {rows.length} rows).
        </div>
      )}

      {rows.length === 0 ? (
        <div className="text-center py-8 bg-subtle border border-border rounded-lg text-muted text-sm">
          Query returned zero rows.
        </div>
      ) : (
        <div className="overflow-x-auto border border-border rounded-lg">
          <table className="min-w-full divide-y divide-border text-sm">
            <thead className="bg-subtle">
              <tr>
                {columns.map((col, idx) => {
                  const isSorted = sortCol === col.name;
                  const ariaSortValue = isSorted
                    ? sortDir === 'asc'
                      ? 'ascending'
                      : 'descending'
                    : 'none';

                  return (
                    <th
                      key={`${col.name}-${idx}`}
                      scope="col"
                      aria-sort={ariaSortValue}
                      className="px-4 py-2.5 text-left text-xs font-semibold text-text"
                    >
                      <button
                        onClick={() => handleSort(col.name)}
                        className="btn-link text-muted"
                        aria-label={`Sort by ${col.name}`}
                      >
                        <span>{col.name}</span>
                        <span className="text-dim text-xs" aria-hidden="true">
                          {isSorted ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
                        </span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="bg-surface divide-y divide-border">
              {sortedRows.map((row, rIdx) => (
                <tr key={rIdx} className="hover:bg-subtle transition-colors">
                  {columns.map((col, cIdx) => (
                    <td
                      key={`${rIdx}-${col.name}-${cIdx}`}
                      className="px-4 py-2 text-text font-mono text-xs whitespace-nowrap"
                    >
                      {row[col.name] === null || row[col.name] === undefined ? (
                        <span className="text-dim italic">null</span>
                      ) : (
                        String(row[col.name])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default DataGrid;
