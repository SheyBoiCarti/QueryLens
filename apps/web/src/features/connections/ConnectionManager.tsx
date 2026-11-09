import React, { useEffect, useState } from 'react';
import { useDatabaseBreadcrumb } from '../../components/AppShell.tsx';
import { api } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';
import ConnectionForm from './ConnectionForm.tsx';
import ConnectionList from './ConnectionList.tsx';
import { VisibilityEditor } from './VisibilityEditor.tsx';

interface ConnectionManagerProps {
  onConnectionDeleted?: (id: string) => void;
}

export function ConnectionManager({ onConnectionDeleted }: ConnectionManagerProps): React.JSX.Element {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configuring, setConfiguring] = useState<ConnectionResponse | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedConnection, setSelectedConnection] = useState<ConnectionResponse | null>(null);

  const breadcrumbConnection = selectedConnection ?? configuring ?? connections[0];
  useDatabaseBreadcrumb(breadcrumbConnection?.database, Object.keys(breadcrumbConnection?.allowed_tables ?? {})[0]?.split('.')[0]);

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
      {(isEditing || configuring) && <div className="page-header">
        <div><h1 className="page-title">Connections</h1><p className="page-subtitle">Manage the databases available to your workspace.</p></div>
      </div>}
      {error && (
        <div role="alert" className="bg-surface border border-danger-border text-danger text-xs p-3 rounded-md">
          {error}
        </div>
      )}

      {configuring ? (
        <VisibilityEditor connection={configuring} onDone={() => { setConfiguring(null); void fetchConnections(); }} />
      ) : loading && connections.length === 0 ? (
        <div className="text-center py-10 text-muted text-sm">Loading connections...</div>
      ) : isEditing ? (
        <ConnectionForm connection={selectedConnection} onSuccess={handleFormSuccess} onCancel={handleCancelForm} />
      ) : (
        <ConnectionList
          connections={connections}
          onRefresh={fetchConnections}
          onAddNew={handleAddNew}
          onEdit={(connection) => { setSelectedConnection(connection); setIsEditing(true); }}
          onConfigure={setConfiguring}
          onDeleted={onConnectionDeleted}
        />
      )}
    </div>
  );
}

export default ConnectionManager;
