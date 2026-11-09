import React, { useState } from 'react';
import { Database, Plus } from 'lucide-react';
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
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Connections</h1>
          <p className="page-subtitle">Manage the databases available to your workspace.</p>
        </div>
        <button onClick={onAddNew} className="btn-primary"><Plus size={16} aria-hidden="true" />Add connection</button>
      </div>
      {connections.length === 0 ? (
        <div className="card text-center py-12 text-muted">No database connections configured yet.</div>
      ) : (
        <div className="space-y-3">
          {connections.map((c) => (
            <div key={c.id} className="card connection-row">
              <div className="icon-tile"><Database size={20} strokeWidth={1.5} aria-hidden="true" /></div>
              <div className="connection-info">
                <div className="actions">
                  <h2 className="section-title">{c.name}</h2>
                  <span className="badge">{c.engine === 'postgresql' ? 'PostgreSQL' : 'MySQL'}</span>
                  {c.tls_enabled && <span className="badge badge-success">TLS</span>}
                </div>
                <p className="connection-address">{c.username}@{c.host}:{c.port}/{c.database}</p>
                {testResult && testResult.id === c.id && (
                  <p role={testResult.success ? 'status' : 'alert'} className={`mt-2 text-xs ${testResult.success ? 'text-accent' : 'text-danger'}`}>
                    {testResult.msg}
                  </p>
                )}
              </div>
              <div className="actions">
                {onEdit && <button onClick={() => onEdit(c)}>Edit</button>}
                {onConfigure && <button onClick={() => onConfigure(c)}>Select tables</button>}
                <button onClick={() => handleTest(c.id)} disabled={testingId === c.id}>
                  {testingId === c.id ? 'Testing...' : 'Test connection'}
                </button>
                <button onClick={() => handleDelete(c.id)} className="btn-danger">Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ConnectionList;
