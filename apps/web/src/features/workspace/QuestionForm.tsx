import React, { useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';

interface QuestionFormProps {
  connections: ConnectionResponse[];
  selectedConnectionId: string;
  onSelectConnection: (id: string) => void;
  onQuerySubmitted: (queryId: string) => void;
  disabled?: boolean;
}

export function QuestionForm({
  connections,
  selectedConnectionId,
  onSelectConnection,
  onQuerySubmitted,
  disabled = false,
}: QuestionFormProps): React.JSX.Element {
  const [question, setQuestion] = useState('');
  const [maxRows, setMaxRows] = useState(100);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    setError(null);
    setLoading(true);

    try {
      const res = await api.post<{ query_id: string; status: string }>('/api/v1/queries', {
        connection_id: selectedConnectionId,
        question: question.trim(),
        max_rows: maxRows,
      });
      onQuerySubmitted(res.query_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to submit query');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow border border-slate-200 p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <label htmlFor="conn-select" className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
            Database Source
          </label>
          <select
            id="conn-select"
            value={selectedConnectionId}
            onChange={(e) => onSelectConnection(e.target.value)}
            disabled={disabled || loading}
            className="px-3 py-1.5 border border-slate-300 rounded text-sm bg-white"
          >
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.engine})
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center space-x-2">
          <label htmlFor="max-rows" className="text-xs text-slate-500 font-medium">
            Max Rows:
          </label>
          <select
            id="max-rows"
            value={maxRows}
            onChange={(e) => setMaxRows(Number(e.target.value))}
            disabled={disabled || loading}
            className="px-2 py-1 border border-slate-300 rounded text-xs bg-white"
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={500}>500</option>
            <option value={1000}>1000</option>
          </select>
        </div>
      </div>

      {error && (
        <div role="alert" className="p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label htmlFor="question-input" className="block text-sm font-medium text-slate-700 mb-1">
            Ask a natural-language question
          </label>
          <textarea
            id="question-input"
            rows={3}
            required
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={disabled || loading}
            placeholder="e.g. Which customers placed more than 5 orders last month?"
            className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:ring-indigo-500 focus:border-indigo-500"
          />
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={disabled || loading || !selectedConnectionId}
            className="px-5 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? 'Submitting...' : 'Run Query'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default QuestionForm;
