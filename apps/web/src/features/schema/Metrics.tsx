import React, { useEffect, useRef, useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { api } from '../../api/client.ts';
import { CatalogSnapshot } from '../../api/catalog.ts';
import { MetricResponse } from '../../api/generated/schema.ts';
import { MetricEditor } from './MetricEditor.tsx';

interface MetricsProps { connectionId: string; catalog?: CatalogSnapshot }
export function Metrics(props: MetricsProps): React.JSX.Element {
  return <MetricList key={props.connectionId} {...props} />;
}
function MetricList({ connectionId, catalog }: MetricsProps): React.JSX.Element {
  const [items, setItems] = useState<MetricResponse[]>([]);
  const [editing, setEditing] = useState<MetricResponse | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    api.get<MetricResponse[]>(`/api/v1/connections/${connectionId}/metrics`, { signal: abort.signal }).then((data) => {
      if (!abort.signal.aborted) { setItems(data); setError(null); }
    }).catch((err: unknown) => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load metric definitions'); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [connectionId, version]);
  const remove = async (id: string) => {
    try {
      await api.delete(`/api/v1/connections/${connectionId}/metrics/${id}`);
      if (mounted.current) setVersion((value) => value + 1);
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : 'Could not remove metric'); }
  };
  return <section className="card space-y-3">
    <h2 className="section-title">Business metrics</h2>
    {error && <p role="alert">{error}</p>}
    {loading && <p role="status">Loading metrics...</p>}
    {items.map((item) => <div key={item.id} className="metric-row">
      <div className="metric-details"><div className="metric-heading"><span className="font-medium">{item.name}</span> <code>({item.key})</code>{!item.enabled && <span className="badge">Disabled</span>}</div>
        {item.description && <p className="text-sm text-muted">{item.description}</p>}
        {!!item.dsl.synonyms?.length && <p className="text-sm">Also called: {item.dsl.synonyms.join(', ')}</p>}
        <p className="font-mono text-xs">{item.dsl.table}.{item.dsl.measure_column} · {item.dsl.aggregation}{item.dsl.units ? ` · ${item.dsl.units}` : ''} · version {item.version}</p>
      </div>
      <div className="metric-actions">
        <button aria-label={`Edit ${item.name}`} className="metric-action" disabled={loading || editing !== null || catalog?.connection_id !== connectionId} onClick={() => setEditing(item)}><Pencil size={14} aria-hidden="true" />Edit</button>
        <button aria-label={`Delete metric ${item.name}`} className="metric-action metric-delete" disabled={editing !== null} onClick={() => void remove(item.id)}><Trash2 size={14} aria-hidden="true" />Delete</button>
      </div>
    </div>)}
    {editing ? <MetricEditor connectionId={connectionId} catalog={catalog} metric={editing === 'new' ? undefined : editing} onSaved={() => { setEditing(null); setVersion((value) => value + 1); }} onCancel={() => {
      setEditing(null);
      setItems([]);
      setLoading(true);
      setVersion((value) => value + 1);
    }} />
      : <button disabled={catalog?.connection_id !== connectionId} className="text-accent underline btn-link" onClick={() => setEditing('new')}>Define metric</button>}
  </section>;
}
