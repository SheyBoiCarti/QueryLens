import React, { useEffect, useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';
import TableDetails from './TableDetails.tsx';

interface SchemaExplorerProps {
  connectionId?: string;
  onConnectionChange?: (id: string) => void;
}

export function SchemaExplorer({ connectionId: initialConnectionId, onConnectionChange }: SchemaExplorerProps): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState<string>(initialConnectionId || '');
  const [catalog, setCatalog] = useState<any | null>(null);
  const [selectedTable, setSelectedTable] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load available connections
  useEffect(() => {
    let isMounted = true;
    api.get<ConnectionResponse[]>('/api/v1/connections')
      .then((conns) => {
        if (!isMounted) return;
        setConnections(conns);
        if (!activeConnectionId && conns.length > 0) {
          const defaultId = initialConnectionId && conns.some(c => c.id === initialConnectionId)
            ? initialConnectionId
            : conns[0].id;
          setActiveConnectionId(defaultId);
          onConnectionChange?.(defaultId);
        }
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err instanceof ApiError ? err.message : 'Failed to load connections');
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // Update active connection if prop changes from outside
  useEffect(() => {
    if (initialConnectionId && initialConnectionId !== activeConnectionId) {
      setActiveConnectionId(initialConnectionId);
    }
  }, [initialConnectionId]);

  const fetchCatalog = async (connId: string) => {
    if (!connId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<any>(`/api/v1/connections/${connId}/schema`);
      setCatalog(data);
      if (data?.tables?.length > 0) {
        setSelectedTable(data.tables[0]);
      } else {
        setSelectedTable(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load catalog');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    if (!activeConnectionId) return;
    setLoading(true);
    try {
      const refreshed = await api.post<any>(`/api/v1/connections/${activeConnectionId}/schema/refresh`);
      setCatalog(refreshed);
      if (refreshed?.tables?.length > 0) {
        setSelectedTable(refreshed.tables[0]);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Refresh failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeConnectionId) {
      fetchCatalog(activeConnectionId);
    }
  }, [activeConnectionId]);

  const handleSelectConnection = (connId: string) => {
    setActiveConnectionId(connId);
    onConnectionChange?.(connId);
  };

  if (!loading && connections.length === 0 && !activeConnectionId) {
    return (
      <div className="bg-white rounded-lg border border-dashed border-slate-300 p-12 text-center text-slate-500 space-y-2">
        <p className="font-semibold text-slate-700">No Database Connections Found</p>
        <p className="text-sm">Please configure a database connection in the Connections tab to explore its schema.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Schema Explorer</h2>
          <p className="text-xs text-slate-500 font-mono">
            {catalog ? `Snapshot Hash: ${catalog.snapshot_hash?.slice(0, 16)}... | Policy v${catalog.policy_version}` : 'Loading schema metadata...'}
          </p>
        </div>

        <div className="flex items-center space-x-3">
          {connections.length > 0 && (
            <div className="flex items-center space-x-2">
              <label htmlFor="schema-conn-select" className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Database:
              </label>
              <select
                id="schema-conn-select"
                value={activeConnectionId}
                onChange={(e) => handleSelectConnection(e.target.value)}
                className="px-3 py-1.5 bg-white border border-slate-300 rounded text-xs font-medium text-slate-700 shadow-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.engine})
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            onClick={handleRefresh}
            disabled={loading || !activeConnectionId}
            className="px-3 py-1.5 bg-white border border-slate-300 rounded text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition"
          >
            {loading ? 'Refreshing...' : 'Refresh Schema'}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">
          {error}
        </div>
      )}

      {catalog && catalog.tables?.length === 0 ? (
        <div className="bg-white rounded-lg border border-dashed border-slate-300 p-12 text-center text-slate-500">
          <p className="font-medium text-slate-700 mb-1">No tables currently visible</p>
          <p className="text-sm">Configure allowed tables and columns in the connection settings to enable analysis.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-2">
            <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Visible Tables</h4>
            <div className="space-y-1 max-h-[600px] overflow-y-auto">
              {catalog?.tables?.map((t: any) => (
                <button
                  key={t.name}
                  onClick={() => setSelectedTable(t)}
                  className={`w-full text-left px-3 py-2 rounded text-sm font-medium transition-colors ${
                    selectedTable?.name === t.name
                      ? 'bg-indigo-50 text-indigo-700 font-semibold border-l-4 border-indigo-600'
                      : 'text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </div>

          <div className="md:col-span-3">
            {selectedTable ? (
              <TableDetails table={selectedTable} />
            ) : (
              <div className="bg-white rounded-lg border border-slate-200 p-12 text-center text-slate-400">
                Select a table to view columns and relationships.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default SchemaExplorer;
