import React, { useEffect, useState } from 'react';
import { api } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';
import ConnectionForm from './ConnectionForm.tsx';
import ConnectionList from './ConnectionList.tsx';
import { VisibilityEditor } from './VisibilityEditor.tsx';

export function ConnectionManager(): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configuring, setConfiguring] = useState<ConnectionResponse | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedConnection, setSelectedConnection] = useState<ConnectionResponse | null>(null);

  const fetchConnections = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.get<ConnectionResponse[]>('/api/v1/connections');
      setConnections(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load connections');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConnections();
  }, []);

  const handleAddNew = () => {
    setSelectedConnection(null);
    setIsEditing(true);
  };

  const handleFormSuccess = (saved: ConnectionResponse) => {
    setConfiguring(saved);
    setIsEditing(false);
    setSelectedConnection(null);
    fetchConnections();
  };

  const handleCancelForm = () => {
    setIsEditing(false);
    setSelectedConnection(null);
  };

  return (
    <div className="space-y-6" data-testid="connection-manager">
      {error && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 text-xs p-3 rounded-md">
          {error}
        </div>
      )}

      {configuring ? (
        <VisibilityEditor connection={configuring} onDone={() => { setConfiguring(null); void fetchConnections(); }} />
      ) : loading && connections.length === 0 ? (
        <div className="text-center py-10 text-slate-500 text-sm">Loading connections...</div>
      ) : isEditing ? (
        <div className="bg-white rounded-lg shadow-sm border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-4 pb-2 border-b border-slate-100">
            <h3 className="text-base font-bold text-slate-900">
              {selectedConnection ? `Edit Connection: ${selectedConnection.name}` : 'New Database Connection'}
            </h3>
            <button
              onClick={handleCancelForm}
              className="text-xs text-slate-500 hover:text-slate-800"
            >
              Cancel
            </button>
          </div>
          <ConnectionForm connection={selectedConnection} onSuccess={handleFormSuccess} onCancel={handleCancelForm} />
        </div>
      ) : (
        <ConnectionList
          connections={connections}
          onRefresh={fetchConnections}
          onAddNew={handleAddNew}
          onEdit={(connection) => { setSelectedConnection(connection); setIsEditing(true); }}
          onConfigure={setConfiguring}
        />
      )}
    </div>
  );
}

export default ConnectionManager;
