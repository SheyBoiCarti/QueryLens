import React, { useEffect, useState } from 'react';
import { api } from '../../api/client.ts';
import {
  SavedQuestionDetail,
  SavedQuestionListResponse,
  SavedQuestionSummary,
} from '../../api/generated/schema.ts';
import { SavedQuestionFilters } from './SavedQuestionFilters.tsx';

export interface SavedQuestionsManagerProps {
  connectionId: string;
  onRunAccepted: (queryId: string) => void;
  onClose?: () => void;
}

export function SavedQuestionsManager({
  connectionId,
  onRunAccepted,
  onClose,
}: SavedQuestionsManagerProps): React.JSX.Element {
  const [items, setItems] = useState<SavedQuestionSummary[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<SavedQuestionDetail | null>(null);
  const [filterValues, setFilterValues] = useState<Record<string, unknown>>({});
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const fetchItems = async () => {
    setLoading(true);
    setError(null);
    try {
      const q = search.trim() ? `&query=${encodeURIComponent(search.trim())}` : '';
      const res = await api.get<SavedQuestionListResponse>(
        `/api/v1/saved-questions?connection_id=${encodeURIComponent(connectionId)}${q}`
      );
      setItems(res.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load saved questions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
    setSelectedId(null);
    setSelectedDetail(null);
  }, [connectionId]);

  const loadDetail = async (id: string) => {
    setSelectedId(id);
    setRunError(null);
    try {
      const detail = await api.get<SavedQuestionDetail>(`/api/v1/saved-questions/${id}`);
      setSelectedDetail(detail);

      // Initialize filter values from defaults
      const defaults: Record<string, unknown> = {};
      detail.parameters.forEach((p) => {
        if (p.default_value !== undefined) {
          defaults[p.name] = p.default_value;
        } else if (p.param_type === 'date_range') {
          defaults[p.name] = { mode: 'this_month' };
        } else if (p.param_type === 'result_count') {
          defaults[p.name] = 100;
        }
      });
      setFilterValues(defaults);
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : 'Failed to load question details');
    }
  };

  const handleRun = async () => {
    if (!selectedDetail) return;
    setRunning(true);
    setRunError(null);
    try {
      const res = await api.post<{ query_id: string; status: string }>(
        `/api/v1/saved-questions/${selectedDetail.id}/run`,
        {
          parameters: filterValues,
          expected_revision: selectedDetail.revision,
        }
      );
      onRunAccepted(res.query_id);
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : 'Failed to execute saved question');
    } finally {
      setRunning(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('Are you sure you want to delete this saved question?')) return;
    try {
      await api.delete(`/api/v1/saved-questions/${id}`);
      if (selectedId === id) {
        setSelectedId(null);
        setSelectedDetail(null);
      }
      fetchItems();
    } catch (err: unknown) {
      alert(`Delete failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const handleDuplicate = async (id: string, currentTitle: string) => {
    try {
      await api.post(`/api/v1/saved-questions/${id}/duplicate`, {
        title: `${currentTitle} (Copy)`,
      });
      fetchItems();
    } catch (err: unknown) {
      alert(`Duplicate failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-6 space-y-6" data-testid="saved-questions-manager">
      <div className="flex items-center justify-between border-b pb-4">
        <div>
          <h3 className="text-lg font-bold text-slate-900">Saved Questions</h3>
          <p className="text-xs text-slate-500">Parameterized queries with direct database execution.</p>
        </div>
        {onClose && (
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg">
            &times;
          </button>
        )}
      </div>

      {error && (
        <div role="alert" className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">
          {error}
        </div>
      )}

      {/* Search Bar */}
      <div className="flex space-x-2">
        <input
          type="search"
          placeholder="Search saved questions..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-3 py-1.5 border border-slate-300 rounded text-sm focus:outline-none focus:border-indigo-500"
        />
        <button
          type="button"
          onClick={fetchItems}
          className="px-4 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded"
        >
          Search
        </button>
      </div>

      {/* Two Column Layout: List and Detail/Filters */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Saved Questions List */}
        <div className="space-y-3">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">
            Questions ({items.length})
          </span>

          {loading ? (
            <p role="status" className="text-sm text-slate-500 py-4">Loading questions...</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-slate-400 py-4 italic">No saved questions found for this connection.</p>
          ) : (
            <div className="divide-y divide-slate-100 border border-slate-200 rounded-lg max-h-96 overflow-y-auto">
              {items.map((item) => (
                <div
                  key={item.id}
                  className={`p-3 space-y-1 transition-colors ${
                    selectedId === item.id ? 'bg-indigo-50 border-l-4 border-indigo-600' : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <h4 className="text-sm font-semibold text-slate-800">{item.title}</h4>
                    <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">
                      rev {item.revision}
                    </span>
                  </div>
                  {item.description && (
                    <p className="text-xs text-slate-500 line-clamp-2">{item.description}</p>
                  )}
                  <div className="flex items-center justify-between pt-2 text-xs">
                    <button
                      type="button"
                      onClick={() => loadDetail(item.id)}
                      className="text-indigo-600 hover:text-indigo-800 font-medium underline"
                    >
                      View or Run
                    </button>
                    <div className="flex items-center space-x-2">
                      <button
                        type="button"
                        onClick={() => handleDuplicate(item.id, item.title)}
                        className="text-slate-500 hover:text-slate-700 underline text-[11px]"
                      >
                        Duplicate
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(item.id)}
                        className="text-rose-500 hover:text-rose-700 underline text-[11px]"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Selected Question Detail & Filters */}
        <div>
          {selectedDetail ? (
            <div className="space-y-4">
              <div className="border-b pb-3">
                <h4 className="text-base font-bold text-slate-900">{selectedDetail.title}</h4>
                {selectedDetail.description && (
                  <p className="text-xs text-slate-600 mt-1">{selectedDetail.description}</p>
                )}
                <span className="text-[10px] text-slate-400 font-mono mt-1 block">
                  Revision: {selectedDetail.revision} | Created: {new Date(selectedDetail.created_at).toLocaleDateString()}
                </span>
              </div>

              {runError && (
                <div role="alert" className="p-3 bg-rose-50 border border-rose-200 text-rose-800 text-xs rounded">
                  {runError}
                </div>
              )}

              <SavedQuestionFilters
                parameters={selectedDetail.parameters}
                values={filterValues}
                onChange={(name, val) => setFilterValues((prev) => ({ ...prev, [name]: val }))}
                onRun={handleRun}
                disabled={running}
              />
            </div>
          ) : (
            <div className="h-full flex items-center justify-center p-8 border border-dashed rounded-lg text-slate-400 text-xs text-center">
              Select a saved question on the left to configure filters and run.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default SavedQuestionsManager;
