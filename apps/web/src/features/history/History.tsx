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
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Query History</h2>
          <p className="text-xs text-slate-500">
            Durable record of previous queries, attempt diagnostics, and volatile cache availability (7-day retention).
          </p>
        </div>

        <button
          onClick={() => fetchHistory()}
          disabled={loading}
          className="px-3 py-1.5 border border-slate-300 rounded-md text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 text-xs p-3 rounded-md">
          {error}
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="text-center py-10 text-slate-400 text-sm">Loading history...</div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 bg-slate-50 border border-slate-200 rounded-lg text-slate-500 text-sm">
          No query runs recorded yet.
        </div>
      ) : (
        <div className="border border-slate-200 rounded-lg shadow-sm overflow-hidden bg-white">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-xs font-semibold text-slate-600">
              <tr>
                <th className="px-4 py-3 text-left">Question</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Cache</th>
                <th className="px-4 py-3 text-left">Created At</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-slate-900 max-w-xs truncate">
                    {item.question}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium uppercase ${
                        item.status === 'completed'
                          ? 'bg-emerald-100 text-emerald-800'
                          : item.status === 'rejected'
                          ? 'bg-rose-100 text-rose-800'
                          : item.status === 'clarification_required'
                          ? 'bg-indigo-100 text-indigo-800'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {item.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {item.results_available ? (
                      <span className="text-emerald-600 font-medium">Cached (Available)</span>
                    ) : (
                      <span className="text-slate-400 italic">Expired / None</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 font-mono">
                    {new Date(item.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    {onSelectRun && (
                      <button
                        onClick={() => onSelectRun(item.id)}
                        className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                      >
                        Inspect
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="text-xs text-rose-600 hover:text-rose-800 font-medium"
                      aria-label={`Delete query ${item.id}`}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {nextCursor && (
            <div className="p-3 border-t border-slate-200 bg-slate-50 flex justify-end">
              <button
                onClick={() => fetchHistory(nextCursor)}
                disabled={loading}
                className="px-3 py-1.5 bg-white border border-slate-300 rounded text-xs font-medium text-slate-700 hover:bg-slate-100"
              >
                Load Next Page â†’
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default History;
