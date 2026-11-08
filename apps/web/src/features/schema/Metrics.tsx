import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client.ts';
import { MetricEditor } from './MetricEditor.tsx';

interface Metric {
  id: string;
  key: string;
  name: string;
  description: string | null;
}

export function Metrics({ connectionId }: { connectionId: string }): React.JSX.Element {
  const [items, setItems] = useState<Metric[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setItems(await api.get<Metric[]>(`/api/v1/connections/${connectionId}/metrics`));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load metric definitions');
    }
  }, [connectionId]);
  useEffect(() => { void load(); }, [load]);
  const remove = async (id: string) => {
    try {
      await api.delete(`/api/v1/connections/${connectionId}/metrics/${id}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove metric');
    }
  };
  return <section className="space-y-3 border rounded bg-white p-4">
    <h3 className="font-semibold">Business metrics</h3>
    {error && <p role="alert">{error}</p>}
    {items.map((item) => <div key={item.id} className="flex justify-between">
      <span>{item.name} ({item.key})</span><button className="text-red-700" onClick={() => void remove(item.id)}>Delete metric</button>
    </div>)}
    {editing ? <MetricEditor connectionId={connectionId} onSaved={() => { setEditing(false); void load(); }} onCancel={() => setEditing(false)} />
      : <button className="text-indigo-700 underline" onClick={() => setEditing(true)}>Define metric</button>}
  </section>;
}
