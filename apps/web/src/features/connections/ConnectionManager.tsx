import React, { useEffect, useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';
import ConnectionForm from './ConnectionForm.tsx';
import ConnectionList from './ConnectionList.tsx';

export function ConnectionManager(): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedConnection, setSelectedConnection] = useState<ConnectionResponse | null>(null);

  const fetchConnections = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.get<ConnectionResponse[]>('/api/v1/connections');
      setConnections(data);
    } catch (err: any) {
      setError(err?.message || 'Failed to load connections');
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

  const handleFormSuccess = () => {
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

      {loading && connections.length === 0 ? (
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
          <ConnectionForm onSuccess={handleFormSuccess} />
        </div>
      ) : (
        <ConnectionList
          connections={connections}
          onRefresh={fetchConnections}
          onAddNew={handleAddNew}
        />
      )}
    </div>
  );
}

export default ConnectionManager;
