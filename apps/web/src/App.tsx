import React, { useState } from 'react';
import { AppShell } from './components/AppShell.tsx';
import { WorkspaceView } from './features/workspace/WorkspaceView.tsx';
import { ConnectionManager } from './features/connections/ConnectionManager.tsx';
import { SchemaExplorer } from './features/schema/SchemaExplorer.tsx';
import { History } from './features/history/History.tsx';
import { AppRoute, useRouter } from './router.tsx';

export type HealthStatus = 'loading' | 'connected' | 'offline' | 'degraded';
export type ActiveTab = AppRoute;

export function App(): React.JSX.Element {
  const { route, navigate } = useRouter();
  const [connectionId, setConnectionId] = useState('');
  const [queryId, setQueryId] = useState<string | null>(null);

  return (
    <AppShell currentRoute={route} onRouteChange={(next) => navigate(next as AppRoute)}>
          {(route === 'ask' || route === 'diagnostics') && (
            <WorkspaceView initialQueryId={queryId} onActiveQueryChange={setQueryId}
              onNavigateToConnections={() => navigate('connections')} />
          )}
          {route === 'connections' && <ConnectionManager />}
          {route === 'schema' && <SchemaExplorer connectionId={connectionId} onConnectionChange={setConnectionId} />}
          {route === 'history' && <History onSelectRun={(id) => { setQueryId(id); navigate('ask'); }} />}
    </AppShell>
  );
}

export default App;
