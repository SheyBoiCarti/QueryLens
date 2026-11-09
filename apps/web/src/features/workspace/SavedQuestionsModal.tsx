import React, { useEffect, useState } from 'react';
import { ParameterDefinitionEditor } from './ParameterDefinitionEditor.tsx';
import { api, ApiError } from '../../api/client.ts';
import {
  ParameterDefinition,
  ParameterDiscoveryResponse,
  SavedQuestionDetail,
} from '../../api/generated/schema.ts';

export interface SavedQuestionsModalProps {
  sourceQueryId: string;
  onClose: () => void;
  onSaved?: (savedQuestion: SavedQuestionDetail) => void;
}

export function SavedQuestionsModal({
  sourceQueryId,
  onClose,
  onSaved,
}: SavedQuestionsModalProps): React.JSX.Element {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [parametersValid, setParametersValid] = useState(true);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [chartPreference, setChartPreference] = useState('');
  const [parameters, setParameters] = useState<ParameterDefinition[]>([]);
  const [selectedSlots, setSelectedSlots] = useState<Set<string>>(new Set());

  useEffect(() => {
    let aborted = false;
    api.get<ParameterDiscoveryResponse>(`/api/v1/queries/${sourceQueryId}/parameters`)
      .then((disc) => {
        if (aborted) return;
        setParameters(disc.definitions);
        setSelectedSlots(new Set(disc.definitions.map((definition) => definition.slot_id)));
      })
      .catch((err: unknown) => {
        if (aborted) return;
        setError(err instanceof Error ? err.message : 'Failed to discover query parameters');
      })
      .finally(() => {
        if (!aborted) setLoading(false);
      });
    return () => {
      aborted = true;
    };
  }, [sourceQueryId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;

    setSaving(true);
    setError(null);
    try {
      const res = await api.post<SavedQuestionDetail>('/api/v1/saved-questions', {
        source_query_id: sourceQueryId,
        title: title.trim(),
        description: description.trim() || null,
        chart_preference: chartPreference || null,
        parameters: parameters.filter((parameter) => selectedSlots.has(parameter.slot_id)),
      });
      onSaved?.(res);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.message : 'Failed to save question');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-40 p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 space-y-6">
        <div className="flex items-center justify-between border-b pb-3">
          <h3 id="modal-title" className="text-lg font-bold text-slate-900">
            Save as Reusable Question
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-lg leading-none"
          >
            &times;
          </button>
        </div>

        {error && (
          <div role="alert" className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded">
            {error}
          </div>
        )}

        {loading ? (
          <p role="status" className="text-sm text-slate-500 py-6 text-center">
            Discovering query parameter slots...
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="saved-title" className="block text-xs font-semibold text-slate-700 mb-1">
                Title <span className="text-rose-500">*</span>
              </label>
              <input
                id="saved-title"
                type="text"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Monthly Active Users by Region"
                className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div>
              <label htmlFor="saved-desc" className="block text-xs font-semibold text-slate-700 mb-1">
                Description
              </label>
              <textarea
                id="saved-desc"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief explanation for teammates"
                className="w-full px-3 py-2 border border-slate-300 rounded text-sm focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="chart-pref" className="block text-xs font-semibold text-slate-700 mb-1">
                  Chart Preference
                </label>
                <select
                  id="chart-pref"
                  value={chartPreference}
                  onChange={(e) => setChartPreference(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm bg-white"
                >
                  <option value="">Auto (Default)</option>
                  <option value="table">Table</option>
                  <option value="line">Line Chart</option>
                  <option value="bar">Bar Chart</option>
                </select>
              </div>
            </div>

            {parameters.length > 0 && (
              <div className="space-y-3 pt-2 border-t">
                <span className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                  Discovered Filter Slots ({parameters.length})
                </span>
                <p className="text-xs text-slate-500">
                  Configure consumer-facing labels and choices for discovered parameters.
                </p>

                <ParameterDefinitionEditor parameters={parameters} onChange={setParameters}
                  selectedSlots={selectedSlots} onSelectionChange={setSelectedSlots} onValidityChange={setParametersValid} />
              </div>
            )}

            <div className="flex justify-end space-x-3 pt-4 border-t">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 border border-slate-300 rounded text-sm text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving || !title.trim() || !parametersValid}
                className="px-4 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save Question'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default SavedQuestionsModal;
