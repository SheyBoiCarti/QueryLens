import React, { useEffect, useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import TableDetails from './TableDetails.tsx';

interface SchemaExplorerProps {
  connectionId: string;
}

export function SchemaExplorer({ connectionId }: SchemaExplorerProps): React.JSX.Element {
  const [catalog, setCatalog] = useState<any | null>(null);
  const [selectedTable, setSelectedTable] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCatalog = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<any>(`/api/v1/connections/${connectionId}/schema`);
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
    setLoading(true);
    try {
      const refreshed = await api.post<any>(`/api/v1/connections/${connectionId}/schema/refresh`);
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
    fetchCatalog();
  }, [connectionId]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Schema Explorer</h2>
          <p className="text-xs text-slate-500 font-mono">
            {catalog ? `Snapshot Hash: ${catalog.snapshot_hash.slice(0, 16)}... | Policy v${catalog.policy_version}` : 'Loading snapshot...'}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="px-3 py-1.5 bg-white border border-slate-300 rounded text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh Schema'}
        </button>
      </div>

      {error && (
        <div role="alert" className="p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">
          {error}
        </div>
      )}

      {catalog && catalog.tables.length === 0 ? (
        <div className="bg-white rounded-lg border border-dashed border-slate-300 p-12 text-center text-slate-500">
          <p className="font-medium text-slate-700 mb-1">No tables currently visible</p>
          <p className="text-sm">Configure allowed tables and columns in the connection settings to enable analysis.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-2">
            <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Visible Tables</h4>
            <div className="space-y-1">
              {catalog?.tables.map((t: any) => (
                <button
                  key={t.name}
                  onClick={() => setSelectedTable(t)}
                  className={`w-full text-left px-3 py-2 rounded text-sm font-medium transition-colors ${
                    selectedTable?.name === t.name
                      ? 'bg-indigo-50 text-indigo-700 font-semibold'
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
