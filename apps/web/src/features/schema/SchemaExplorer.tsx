import React, { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client.ts';
import { CatalogLabelInput, ConnectionResponse } from '../../api/generated/schema.ts';
import { CatalogSnapshot, CatalogTable } from '../../api/catalog.ts';
import { useDatabaseBreadcrumb } from '../../components/AppShell.tsx';
import { Metrics } from './Metrics.tsx';
import { LabelManager, labelFor } from './LabelManager.tsx';

interface SchemaExplorerProps {
  connectionId?: string;
  onConnectionChange?: (id: string) => void;
}

export function SchemaExplorer({ connectionId, onConnectionChange }: SchemaExplorerProps): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [connectionsLoaded, setConnectionsLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState(connectionId || '');
  const activeId = connections.some((item) => item.id === selectedId) ? selectedId : connections[0]?.id || '';
  const [catalog, setCatalog] = useState<CatalogSnapshot | null>(null);
  const [table, setTable] = useState<CatalogTable | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [labels, setLabels] = useState<CatalogLabelInput[]>([]);
  const activeRef = useRef(activeId);
  activeRef.current = activeId;
  const currentCatalog = catalog?.connection_id === activeId ? catalog : null;

  useDatabaseBreadcrumb(connections.find((item) => item.id === activeId)?.database, table?.namespace);

  useEffect(() => {
    const abort = new AbortController();
    api.get<ConnectionResponse[]>('/api/v1/connections', { signal: abort.signal }).then((items) => {
      if (abort.signal.aborted) return;
      setConnections(items);
      setConnectionsLoaded(true);
    }).catch((err: unknown) => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load connections'); });
    return () => abort.abort();
  }, []);

  useEffect(() => { setSelectedId(connectionId || ''); }, [connectionId]);

  useEffect(() => {
    if (connectionsLoaded && activeId !== (connectionId || '')) onConnectionChange?.(activeId);
  }, [activeId, connectionId, connectionsLoaded, onConnectionChange]);

  useEffect(() => {
    if (!activeId) return;
    const abort = new AbortController();
    setLoading(true);
    setError(null);
    setCatalog(null);
    setTable(null);
    setLabels([]);
    setRefreshing(false);
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
    const refreshId = activeId;
    setRefreshing(true);
    setError(null);
    try {
      await api.post<CatalogSnapshot>(`/api/v1/connections/${activeId}/schema/refresh`);
      if (activeRef.current === refreshId) setVersion((value) => value + 1);
    } catch (err) {
      if (activeRef.current === refreshId) setError(err instanceof Error ? err.message : 'Could not refresh schema');
    } finally {
      if (activeRef.current === refreshId) setRefreshing(false);
    }
  };

  return <div className="space-y-5">
    <div className="page-header">
      <div><h1 className="page-title">Explore schema</h1><p className="page-subtitle">Explore tables and give your data business context.</p></div>
      <div className="actions">
        <label className="flex items-center gap-2">Database <select aria-label="Schema database" value={activeId} onChange={(event) => {
          setSelectedId(event.target.value); onConnectionChange?.(event.target.value);
        }}>
          {connections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <button disabled={!activeId || refreshing || loading} onClick={() => void refresh()}>{refreshing ? 'Refreshing...' : 'Refresh schema'}</button>
      </div>
    </div>
    {error && <p role="alert" className="text-danger">{error}</p>}
    {loading && <p role="status">Loading schema...</p>}
    {currentCatalog && <p className="text-xs text-muted font-mono">Snapshot {currentCatalog.snapshot_hash.slice(0, 16)} · policy {currentCatalog.policy_version}</p>}
    {currentCatalog?.tables.length === 0 && <p>Select allowed tables and columns in Connections to enable analytics.</p>}
    {currentCatalog && currentCatalog.tables.length > 0 && <div className="schema-grid">
      <nav aria-label="Visible tables" className="card schema-list">
        {currentCatalog.tables.map((item) => <button key={`${item.namespace}.${item.name}`} aria-current={table?.name === item.name && table?.namespace === item.namespace ? true : undefined}
          onClick={() => setTable(item)}>{labelFor(labels, item.namespace, item.name)?.display_name && <span className="block font-semibold">{labelFor(labels, item.namespace, item.name)?.display_name}</span>}<span className="font-mono text-xs">{item.namespace}.{item.name}</span></button>)}
      </nav>
      <LabelManager key={`labels:${activeId}:${version}`} connectionId={activeId} tables={currentCatalog.tables} selectedTable={table}
        onLoaded={(data) => { if (activeRef.current === activeId) setLabels(data.labels); }}
        onSaved={(data) => { if (activeRef.current === activeId) setLabels(data.labels); }} />
    </div>}
    {connectionsLoaded && !connections.length && <p>Add a database connection in Connections to explore its schema.</p>}
    {activeId && currentCatalog && <Metrics key={`metrics:${activeId}:${version}`} connectionId={activeId} catalog={currentCatalog} />}
  </div>;
}

export default SchemaExplorer;
