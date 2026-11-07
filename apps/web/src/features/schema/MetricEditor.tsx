import React, { useState } from 'react';
import { api, ApiError } from '../../api/client.ts';

interface MetricEditorProps {
  connectionId: string;
  onSaved: () => void;
  onCancel: () => void;
}

export function MetricEditor({ connectionId, onSaved, onCancel }: MetricEditorProps): React.JSX.Element {
  const [key, setKey] = useState('');
  const [name, setName] = useState('');
  const [table, setTable] = useState('');
  const [measureColumn, setMeasureColumn] = useState('');
  const [aggregation, setAggregation] = useState<'sum' | 'count' | 'avg' | 'min' | 'max'>('sum');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await api.post(`/api/v1/connections/${connectionId}/metrics`, {
        key: key.toLowerCase().trim(),
        name: name.trim(),
        table: table.trim(),
        measure_column: measureColumn.trim(),
        aggregation,
        filters: [],
        grain: [],
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save metric');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-slate-200 p-6 max-w-lg mx-auto space-y-4">
      <h3 className="text-lg font-bold text-slate-900">Define Business Metric</h3>

      {error && (
        <div role="alert" className="p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
            Metric Key (identifier)
          </label>
          <input
            type="text"
            required
            pattern="^[a-z0-9_]+$"
            placeholder="e.g. net_revenue"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm font-mono"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
            Display Name
          </label>
          <input
            type="text"
            required
            placeholder="e.g. Net Revenue"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
              Table
            </label>
            <input
              type="text"
              required
              placeholder="e.g. orders"
              value={table}
              onChange={(e) => setTable(e.target.value)}
              className="w-full px-3 py-2 border rounded-md text-sm font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
              Measure Column
            </label>
            <input
              type="text"
              required
              placeholder="e.g. amount"
              value={measureColumn}
              onChange={(e) => setMeasureColumn(e.target.value)}
              className="w-full px-3 py-2 border rounded-md text-sm font-mono"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
            Aggregation
          </label>
          <select
            value={aggregation}
            onChange={(e) => setAggregation(e.target.value as any)}
            className="w-full px-3 py-2 border rounded-md text-sm bg-white"
          >
            <option value="sum">SUM</option>
            <option value="count">COUNT</option>
            <option value="avg">AVG</option>
            <option value="min">MIN</option>
            <option value="max">MAX</option>
          </select>
        </div>

        <div className="flex justify-end space-x-3 pt-4 border-t">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 border rounded-md text-sm text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? 'Saving...' : 'Save Metric'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default MetricEditor;
