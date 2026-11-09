import React, { useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';

interface ConnectionListProps {
  connections: ConnectionResponse[];
  onRefresh: () => void;
  onAddNew: () => void;
  onEdit?: (connection: ConnectionResponse) => void;
  onConfigure?: (connection: ConnectionResponse) => void;
  onDeleted?: (id: string) => void;
}

export function ConnectionList({ connections, onRefresh, onAddNew, onEdit, onConfigure, onDeleted }: ConnectionListProps): React.JSX.Element {
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; msg: string } | null>(null);

  const handleTest = async (id: string) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const res = await api.post<{ success: boolean; server_version?: string; message: string }>(
        `/api/v1/connections/${id}/test`
      );
      setTestResult({
        id,
        success: res.success,
        msg: res.success ? `Connected: ${res.server_version}` : res.message,
      });
    } catch (err) {
      setTestResult({
        id,
        success: false,
        msg: err instanceof ApiError ? err.message : 'Test failed',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this connection?')) return;
    try {
      await api.delete(`/api/v1/connections/${id}`);
      onDeleted?.(id);
      onRefresh();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Delete failed');
    }
  };

  return (
    <div className="bg-white rounded-lg shadow border border-slate-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-bold text-slate-900">Configured Database Sources</h3>
          <p className="text-sm text-slate-500">Connected analytics databases (PostgreSQL &amp; MySQL)</p>
        </div>
        <button
          onClick={onAddNew}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-700"
        >
          Add Connection
        </button>
      </div>

      {connections.length === 0 ? (
        <div className="text-center py-12 text-slate-500 border-2 border-dashed rounded-lg">
          No database connections configured yet.
        </div>
      ) : (
        <div className="divide-y divide-slate-200">
          {connections.map((c) => (
            <div key={c.id} className="py-4 flex items-center justify-between">
              <div>
                <div className="flex items-center space-x-2">
                  <span className="font-semibold text-slate-900">{c.name}</span>
                  <span className="text-xs uppercase px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono">
                    {c.engine}
                  </span>
                  {c.tls_enabled && (
                    <span className="text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-700">
                      TLS
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  {c.username}@{c.host}:{c.port}/{c.database}
                </div>
                {testResult && testResult.id === c.id && (
                  <div
                    className={`mt-2 text-xs p-2 rounded ${
                      testResult.success ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'
                    }`}
                  >
                    {testResult.msg}
                  </div>
                )}
              </div>

              <div className="flex items-center space-x-2">
                {onEdit && <button onClick={() => onEdit(c)} className="text-indigo-700 text-sm">Edit</button>}
                {onConfigure && <button onClick={() => onConfigure(c)} className="text-indigo-700 text-sm">Select tables</button>}
                <button
                  onClick={() => handleTest(c.id)}
                  disabled={testingId === c.id}
                  className="px-3 py-1.5 border border-slate-300 rounded text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {testingId === c.id ? 'Testing...' : 'Test Connection'}
                </button>
                <button
                  onClick={() => handleDelete(c.id)}
                  className="px-3 py-1.5 border border-red-200 text-red-600 rounded text-xs font-medium hover:bg-red-50"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ConnectionList;
