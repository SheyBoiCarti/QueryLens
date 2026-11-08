import React, { useEffect, useState } from 'react';
import { api } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';
import { CatalogSnapshot, CatalogTable } from '../../api/catalog.ts';
import TableDetails from './TableDetails.tsx';
import { Metrics } from './Metrics.tsx';

interface SchemaExplorerProps {
  connectionId?: string;
  onConnectionChange?: (id: string) => void;
}

export function SchemaExplorer({ connectionId, onConnectionChange }: SchemaExplorerProps): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [activeId, setActiveId] = useState(connectionId || '');
  const [catalog, setCatalog] = useState<CatalogSnapshot | null>(null);
  const [table, setTable] = useState<CatalogTable | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    api.get<ConnectionResponse[]>('/api/v1/connections', { signal: abort.signal }).then((items) => {
      if (abort.signal.aborted) return;
      setConnections(items);
      setActiveId((current) => current || items[0]?.id || '');
    }).catch((err: unknown) => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load connections'); });
    return () => abort.abort();
  }, []);

  useEffect(() => { if (connectionId) setActiveId(connectionId); }, [connectionId]);

  useEffect(() => {
    if (!activeId) return;
    const abort = new AbortController();
    setLoading(true);
    setError(null);
    setCatalog(null);
    setTable(null);
    api.get<CatalogSnapshot>(`/api/v1/connections/${activeId}/schema`, { signal: abort.signal }).then((data) => {
      if (abort.signal.aborted) return;
      setCatalog(data);
      setTable(data.tables[0] || null);
    }).catch((err: unknown) => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load schema'); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [activeId, version]);

  const refresh = async () => {
    if (!activeId) return;
    setRefreshing(true);
    setError(null);
    try {
      await api.post<CatalogSnapshot>(`/api/v1/connections/${activeId}/schema/refresh`);
      setVersion((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not refresh schema');
    } finally {
      setRefreshing(false);
    }
  };

  return <div className="space-y-5">
    <div className="flex justify-between items-center">
      <h2 className="text-xl font-semibold">Schema explorer</h2>
      <div className="flex gap-4">
        <label>Database <select aria-label="Schema database" value={activeId} onChange={(event) => {
          setActiveId(event.target.value); onConnectionChange?.(event.target.value);
        }}>
          {connections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <button disabled={!activeId || refreshing || loading} onClick={() => void refresh()}>{refreshing ? 'Refreshing...' : 'Refresh schema'}</button>
      </div>
    </div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {loading && <p role="status">Loading schema...</p>}
    {catalog && <p className="text-xs text-slate-500">Snapshot {catalog.snapshot_hash.slice(0, 16)} · policy {catalog.policy_version}</p>}
    {catalog?.tables.length === 0 && <p>Select allowed tables and columns in Connections to enable analytics.</p>}
    {catalog && catalog.tables.length > 0 && <div className="grid grid-cols-4 gap-4">
      <nav aria-label="Visible tables" className="space-y-2">
        {catalog.tables.map((item) => <button key={`${item.namespace}.${item.name}`} className="block text-left text-indigo-700"
          onClick={() => setTable(item)}>{item.namespace}.{item.name}</button>)}
      </nav>
      <div className="col-span-3">{table && <TableDetails table={table} />}</div>
    </div>}
    {activeId && <Metrics key={activeId} connectionId={activeId} />}
  </div>;
}

export default SchemaExplorer;
