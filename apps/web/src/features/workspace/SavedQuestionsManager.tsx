import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client.ts';
import {
  SavedQuestionDetail,
  SavedQuestionListResponse,
  SavedQuestionSummary,
} from '../../api/generated/schema.ts';
import { ParameterDefinitionEditor } from './ParameterDefinitionEditor.tsx';
import { SavedQuestionFilters } from './SavedQuestionFilters.tsx';

export interface SavedQuestionsManagerProps {
  connectionId: string;
  onRunAccepted: (queryId: string) => void;
  onClose?: () => void;
  onAskVariation?: (question: string) => void;
}

export function SavedQuestionsManager({
  connectionId,
  onRunAccepted,
  onClose,
  onAskVariation,
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
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editPreference, setEditPreference] = useState('');
  const [editParameters, setEditParameters] = useState<SavedQuestionDetail['parameters']>([]);
  const [editSlots, setEditSlots] = useState<Set<string>>(new Set());
  const [parametersValid, setParametersValid] = useState(true);
  const [reviewSql, setReviewSql] = useState<string | null>(null);
  const [variation, setVariation] = useState('');
  const [replacementRunId, setReplacementRunId] = useState('');
  const currentConnection = useRef(connectionId);
  currentConnection.current = connectionId;
  const listRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);
  const selectedIdRef = useRef<string | null>(null);

  const fetchItems = useCallback(async (cursor?: string | null, append = false) => {
    listRequest.current?.abort();
    const controller = new AbortController();
    listRequest.current = controller;
    const requestedConnection = connectionId;
    setLoading(true);
    setError(null);
    try {
      const q = search.trim() ? `&search=${encodeURIComponent(search.trim())}` : '';
      const page = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
      const res = await api.get<SavedQuestionListResponse>(
        `/api/v1/saved-questions?connection_id=${encodeURIComponent(requestedConnection)}${q}${page}`,
        { signal: controller.signal }
      );
      if (controller.signal.aborted || listRequest.current !== controller || requestedConnection !== currentConnection.current) return;
      setItems((previous) => append ? [...previous, ...res.items] : res.items);
      setNextCursor(res.next_cursor ?? null);
    } catch (err: unknown) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Failed to load saved questions');
    } finally {
      if (!controller.signal.aborted && listRequest.current === controller) setLoading(false);
    }
  }, [connectionId, search]);

  useEffect(() => {
    selectedIdRef.current = null;
    setSelectedId(null);
    setSelectedDetail(null);
    setFilterValues({});
  }, [connectionId]);

  useEffect(() => {
    void fetchItems();
    return () => {
      listRequest.current?.abort();
      detailRequest.current?.abort();
    };
  }, [fetchItems]);

  const loadDetail = async (id: string) => {
    detailRequest.current?.abort();
    const requestedConnection = connectionId;
    const controller = new AbortController();
    detailRequest.current = controller;
    selectedIdRef.current = id;
    setSelectedId(id);
    setSelectedDetail(null);
    setReviewSql(null);
    setVariation('');
    setRunError(null);
    try {
      const detail = await api.get<SavedQuestionDetail>(`/api/v1/saved-questions/${id}`, { signal: controller.signal });
      if (controller.signal.aborted || detailRequest.current !== controller || selectedIdRef.current !== id || requestedConnection !== currentConnection.current) return;
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
      if (!controller.signal.aborted && detailRequest.current === controller) {
        setRunError(err instanceof Error ? err.message : 'Failed to load question details');
      }
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
      if (selectedDetail.connection_id === currentConnection.current) onRunAccepted(res.query_id);
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : 'Failed to execute saved question');
    } finally {
      setRunning(false);
    }
  };

  const runReview = async () => {
    if (!selectedDetail) return;
    setRunning(true);
    setRunError(null);
    try {
      const result = await api.post<{ query_id: string }>('/api/v1/queries/sql', {
        connection_id: selectedDetail.connection_id,
        sql: reviewSql ?? selectedDetail.canonical_sql_template,
        max_rows: selectedDetail.default_max_rows,
      });
      if (selectedDetail.connection_id === currentConnection.current) onRunAccepted(result.query_id);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Review submission failed');
    } finally {
      setRunning(false);
    }
  };

  const beginEdit = () => {
    if (!selectedDetail) return;
    setEditTitle(selectedDetail.title);
    setEditDescription(selectedDetail.description || '');
    setEditPreference(selectedDetail.chart_preference || '');
    setEditParameters(selectedDetail.parameters);
    setEditSlots(new Set(selectedDetail.parameters.map((parameter) => parameter.slot_id)));
    setParametersValid(true);
    setReplacementRunId('');
    setEditing(true);
  };

  const saveDefinition = async (replacement = false) => {
    if (!selectedDetail) return;
    try {
      const payload = replacement
        ? { expected_revision: selectedDetail.revision, replacement_query_id: replacementRunId.trim() }
        : {
            expected_revision: selectedDetail.revision,
            title: editTitle,
            description: editDescription || null,
            chart_preference: editPreference || null,
            parameters: editParameters.filter((parameter) => editSlots.has(parameter.slot_id)),
          };
      const detail = await api.patch<SavedQuestionDetail>(`/api/v1/saved-questions/${selectedDetail.id}`, payload);
      if (detail.connection_id !== currentConnection.current || selectedIdRef.current !== detail.id) return;
      setSelectedDetail(detail);
      setFilterValues(Object.fromEntries(detail.parameters.map((parameter) => [parameter.name, parameter.default_value])));
      setItems((previous) => previous.map((item) => item.id === detail.id ? { ...item, ...detail } : item));
      setEditing(false);
      setRunError(null);
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : 'Failed to update saved question');
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
          onClick={() => void fetchItems()}
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
              {items.filter((item) => item.connection_id === connectionId).map((item) => (
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
          {!loading && nextCursor && (
            <button type="button" onClick={() => void fetchItems(nextCursor, true)}
              className="w-full py-2 text-sm text-indigo-700 underline">Load more saved questions</button>
          )}
        </div>

        {/* Right: Selected Question Detail & Filters */}
        <div>
          {selectedDetail?.connection_id === connectionId ? (
            <div className="space-y-4">
              <div className="border-b pb-3">
                {editing ? (
                  <div className="space-y-2">
                    <input aria-label="Saved question title" value={editTitle} onChange={(event) => setEditTitle(event.target.value)} className="w-full border rounded px-2 py-1" />
                    <textarea aria-label="Saved question description" value={editDescription} onChange={(event) => setEditDescription(event.target.value)} className="w-full border rounded px-2 py-1" />
                    <select aria-label="Saved chart preference" value={editPreference} onChange={(event) => setEditPreference(event.target.value)} className="border rounded px-2 py-1">
                      <option value="">Auto</option><option value="table">Table</option><option value="line">Line</option><option value="bar">Bar</option>
                    </select>
                    <ParameterDefinitionEditor parameters={editParameters} onChange={setEditParameters}
                      selectedSlots={editSlots} onSelectionChange={setEditSlots} onValidityChange={setParametersValid} />
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={!parametersValid} onClick={() => void saveDefinition()} className="text-indigo-700 underline">Save definition</button>
                      <button type="button" onClick={() => setEditing(false)} className="text-slate-600 underline">Cancel edit</button>
                    </div>
                    <div className="border-t pt-2 space-y-1">
                      <label className="block text-xs">Replace from a successful run ID (explicit revision action)</label>
                      <input aria-label="Successful replacement run" value={replacementRunId} onChange={(event) => setReplacementRunId(event.target.value)} className="w-full border rounded px-2 py-1" />
                      <button type="button" disabled={!replacementRunId.trim()} onClick={() => void saveDefinition(true)} className="text-rose-700 underline disabled:opacity-50">Replace stored SQL from run</button>
                    </div>
                  </div>
                ) : (
                  <>
                <h4 className="text-base font-bold text-slate-900">{selectedDetail.title}</h4>
                {selectedDetail.description && (
                  <p className="text-xs text-slate-600 mt-1">{selectedDetail.description}</p>
                )}
                <span className="text-[10px] text-slate-400 font-mono mt-1 block">
                  Revision: {selectedDetail.revision} | Created: {new Date(selectedDetail.created_at).toLocaleDateString()}
                </span>
                  </>
                )}
              </div>

              {runError && (
                <div role="alert" className="p-3 bg-rose-50 border border-rose-200 text-rose-800 text-xs rounded">
                  {runError}
                </div>
              )}

              <details><summary>Review stored SQL and revision {selectedDetail.revision}</summary>
                <textarea aria-label="SQL for saved question review" className="w-full font-mono text-xs border rounded p-2" rows={6}
                  value={reviewSql ?? selectedDetail.canonical_sql_template} onChange={(event) => setReviewSql(event.target.value)} />
                <button type="button" disabled={running} onClick={() => void runReview()} className="text-indigo-700 underline">Run SQL for review</button>
                <p className="text-xs">Physical or metric changes require a successful run and an explicit replacement below.</p>
              </details>
              {!editing && <SavedQuestionFilters
                parameters={selectedDetail.parameters}
                values={filterValues}
                onChange={(name, val) => setFilterValues((prev) => ({ ...prev, [name]: val }))}
                onRun={handleRun}
                disabled={running}
              />}
              {!editing && <div className="flex flex-wrap gap-3 text-xs">
                <button type="button" onClick={beginEdit} className="text-indigo-700 underline">Edit definition</button>
                {onAskVariation && <label>Variation request
                  <input aria-label="Variation request" value={variation} onChange={(event) => setVariation(event.target.value)} className="border rounded p-1 mx-2" />
                  <button type="button" disabled={!variation.trim()} onClick={() => onAskVariation(`${variation.trim()}\nOriginal scope: ${selectedDetail.effective_question}`)} className="text-indigo-700 underline disabled:opacity-50">Ask for a variation</button>
                </label>}
              </div>}
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
