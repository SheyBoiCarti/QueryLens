import React, { useCallback, useEffect, useState } from 'react';
import { api, ApiError, setCsrfToken } from './api/client.ts';
import { UserResponse } from './api/generated/schema.ts';
import { AppShell } from './components/AppShell.tsx';
import { WorkspaceView } from './features/workspace/WorkspaceView.tsx';
import { ConnectionManager } from './features/connections/ConnectionManager.tsx';
import { SchemaExplorer } from './features/schema/SchemaExplorer.tsx';
import { History } from './features/history/History.tsx';
import { Login } from './features/auth/Login.tsx';
import { AppRoute, useRouter } from './router.tsx';

export type HealthStatus = 'loading' | 'connected' | 'offline' | 'degraded';
export type ActiveTab = AppRoute;

export function App(): React.JSX.Element {
  const { route, navigate } = useRouter();
  const [user, setUser] = useState<UserResponse | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectionId, setConnectionId] = useState('');
  const [queryId, setQueryId] = useState<string | null>(null);

  const clearSession = useCallback(() => {
    setUser(null);
    setCsrfToken(null);
    setConnectionId('');
    setQueryId(null);
  }, []);

  const restoreSession = useCallback(async (signal?: AbortSignal) => {
    setRestoring(true);
    setError(null);
    try {
      const current = await api.getMe({ signal });
      await api.getCsrf({ signal });
      if (!signal?.aborted) setUser(current);
    } catch (err) {
      if (signal?.aborted) return;
      clearSession();
      if (!(err instanceof ApiError && err.statusCode === 401)) {
        setError(err instanceof Error ? err.message : 'Could not connect to QueryLens');
      }
    } finally {
      if (!signal?.aborted) setRestoring(false);
    }
  }, [clearSession]);

  useEffect(() => {
    const abort = new AbortController();
    void restoreSession(abort.signal);
    window.addEventListener('querylens:unauthorized', clearSession);
    return () => { abort.abort(); window.removeEventListener('querylens:unauthorized', clearSession); };
  }, [restoreSession, clearSession]);

  const logout = async () => {
    try {
      await api.logout();
      clearSession();
      navigate('login');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign out failed; please retry');
    }
  };

  return (
    <AppShell currentRoute={route} onRouteChange={(next) => navigate(next as AppRoute)} user={user} onLogout={() => void logout()}>
      {error && <div role="alert" className="p-4 rounded border border-red-200 bg-red-50 text-red-800">
        {error} <button onClick={() => void restoreSession()} className="underline">Reconnect</button>
      </div>}
      {restoring ? <p role="status">Restoring your session...</p> : !user ? (
        <Login onSuccess={(current) => { setUser(current); setError(null); navigate('ask'); }} />
      ) : (
        <>
          {(route === 'ask' || route === 'login' || route === 'diagnostics') && (
            <WorkspaceView initialQueryId={queryId} onActiveQueryChange={setQueryId}
              onNavigateToConnections={() => navigate('connections')} />
          )}
          {route === 'connections' && <ConnectionManager />}
          {route === 'schema' && <SchemaExplorer connectionId={connectionId} onConnectionChange={setConnectionId} />}
          {route === 'history' && <History onSelectRun={(id) => { setQueryId(id); navigate('ask'); }} />}
        </>
      )}
    </AppShell>
  );
}

export default App;
