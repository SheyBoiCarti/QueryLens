import React, { useEffect, useState } from 'react';
import { api } from '../../api/client.ts';

export interface HistoryItem {
  id: string;
  connection_id: string;
  question: string;
  status: string;
  created_at: string;
  max_rows: number;
  results_available: boolean;
}

export interface HistoryProps {
  onSelectRun?: (queryId: string) => void;
}

export function History({ onSelectRun }: HistoryProps): React.JSX.Element {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const fetchHistory = async (cursor?: string) => {
    try {
      setLoading(true);
      setError(null);
      const url = cursor
        ? `/api/v1/queries/history?limit=20&cursor=${encodeURIComponent(cursor)}`
        : '/api/v1/queries/history?limit=20';
      const data = await api.get<{ items: HistoryItem[]; next_cursor: string | null }>(url);
      setItems((previous) => cursor ? [...previous, ...data.items] : data.items);
      setNextCursor(data.next_cursor);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load query history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const handleDelete = async (queryId: string) => {
    if (!confirm('Are you sure you want to delete this query run and its cached results?')) {
      return;
    }
    try {
      await api.delete(`/api/v1/queries/${queryId}`);
      setItems((prev) => prev.filter((item) => item.id !== queryId));
    } catch (err: unknown) {
      alert(`Delete failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  return (
    <div className="space-y-4" data-testid="history-view">
      <div className="page-header">
        <div>
          <h1 className="page-title">History</h1>
          <p className="page-subtitle">
            Review previous questions, inspect runs, and manage cached results.
          </p>
        </div>

        <button
          onClick={() => fetchHistory()}
          disabled={loading}
          className="border rounded-md font-medium text-text"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div role="alert" className="bg-surface border border-danger-border text-danger text-xs p-3 rounded-md">
          {error}
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="text-center py-10 text-dim text-sm">Loading history...</div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 bg-subtle border border-border rounded-lg text-muted text-sm">
          No query runs recorded yet.
        </div>
      ) : (
        <div className="card table-card">
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Query history"><table className="history-table">
            <thead className="bg-subtle text-xs font-semibold text-muted">
              <tr>
                <th scope="col" className="text-left">Question</th>
                <th scope="col" className="text-left">Status</th>
                <th scope="col" className="text-left">Cache</th>
                <th scope="col" className="text-left">Created at</th>
                <th scope="col" className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-subtle transition-colors">
                  <td className="font-medium text-text max-w-xs truncate" title={item.question}>
                    {item.question}
                  </td>
                  <td >
                    <span
                      className={`badge ${item.status === 'completed' ? 'badge-success' : ['rejected', 'failed'].includes(item.status) ? 'badge-danger' : ''}`}
                    >
                      {item.status.charAt(0).toUpperCase() + item.status.slice(1).replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="text-xs">
                    {item.results_available ? (
                      <span className="text-accent font-medium">Cached (available)</span>
                    ) : (
                      <span className="text-dim italic">Expired / none</span>
                    )}
                  </td>
                  <td className="text-xs text-muted font-mono whitespace-nowrap">
                    {new Date(item.created_at).toLocaleString()}
                  </td>
                  <td className="text-right space-x-3 whitespace-nowrap">
                    {onSelectRun && (
                      <button
                        onClick={() => onSelectRun(item.id)}
                        className="btn-link"
                      >
                        Inspect
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="btn-link btn-link-danger"
                      aria-label={`Delete query ${item.id}`}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>

          {nextCursor && (
            <div className="p-3 border-t border-border bg-subtle flex justify-end">
              <button
                onClick={() => fetchHistory(nextCursor)}
                disabled={loading}
                className="border rounded font-medium text-text"
              >
                Load next page →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default History;
