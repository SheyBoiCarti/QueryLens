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
    <div className="card space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="conn-select" className="block text-xs text-muted mb-1">
            Database source
          </label>
          <select
            id="conn-select"
            value={selectedConnectionId}
            onChange={(e) => onSelectConnection(e.target.value)}
            disabled={disabled || loading}
            className="border rounded"
          >
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.engine === 'postgresql' ? 'PostgreSQL' : 'MySQL'})
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="max-rows" className="text-xs text-muted font-medium">
            Max rows
          </label>
          <select
            id="max-rows"
            value={maxRows}
            onChange={(e) => setMaxRows(Number(e.target.value))}
            disabled={disabled || loading}
            className="border rounded"
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={500}>500</option>
            <option value={1000}>1000</option>
          </select>
        </div>
      </div>

      {error && (
        <div role="alert" className="p-3 bg-surface text-danger text-sm rounded border border-danger-border">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label htmlFor="question-input" className="block font-medium mb-1">
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
            className="w-full border rounded-md"
          />
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={disabled || loading || !selectedConnectionId}
            className="btn-primary"
          >
            {loading ? 'Submitting...' : 'Run query'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default QuestionForm;
