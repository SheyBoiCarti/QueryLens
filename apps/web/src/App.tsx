import React, { useEffect, useState } from 'react';
import { api } from './api/client.ts';
import { UserResponse } from './api/generated/schema.ts';
import { WorkspaceView } from './features/workspace/WorkspaceView.tsx';
import { ConnectionManager } from './features/connections/ConnectionManager.tsx';
import { SchemaExplorer } from './features/schema/SchemaExplorer.tsx';
import { History } from './features/history/History.tsx';
import { Login } from './features/auth/Login.tsx';

export type HealthStatus = 'loading' | 'connected' | 'offline' | 'degraded';
export type ActiveTab = 'ask' | 'connections' | 'schema' | 'history' | 'login';

export function App(): React.JSX.Element {
  const [health, setHealth] = useState<HealthStatus>('loading');
  const [metadataStatus, setMetadataStatus] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('ask');
  const [user, setUser] = useState<UserResponse | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string>('');

  const checkHealth = () => {
    fetch('/api/v1/health')
      .then(async (res) => {
        if (res.ok) {
          const data = await res.json();
          setHealth('connected');
          setMetadataStatus(data.metadata_db || 'healthy');
        } else {
          setHealth('degraded');
          setMetadataStatus('unreachable');
        }
      })
      .catch(() => {
        setHealth('offline');
        setMetadataStatus(null);
      });
  };

  useEffect(() => {
    checkHealth();
  }, []);

  const handleLogout = async () => {
    try {
      await api.logout();
      setUser(null);
      setActiveTab('ask');
    } catch {
      setUser(null);
    }
  };

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-800 font-sans">
      {/* Top Navbar */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between sticky top-0 z-20">
        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-3 cursor-pointer" onClick={() => setActiveTab('ask')}>
            <div className="w-8 h-8 rounded bg-indigo-600 flex items-center justify-center text-white font-bold text-lg shadow-sm">
              Q
            </div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900">QueryLens</h1>
          </div>

          <nav aria-label="Main Navigation" className="flex items-center space-x-1">
            <button
              onClick={() => setActiveTab('ask')}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                activeTab === 'ask'
                  ? 'bg-indigo-50 text-indigo-700 font-semibold'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              Ask Data
            </button>
            <button
              onClick={() => setActiveTab('connections')}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                activeTab === 'connections'
                  ? 'bg-indigo-50 text-indigo-700 font-semibold'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              Connections
            </button>
            <button
              onClick={() => setActiveTab('schema')}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                activeTab === 'schema'
                  ? 'bg-indigo-50 text-indigo-700 font-semibold'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              Explore Schema
            </button>
            <button
              onClick={() => setActiveTab('history')}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                activeTab === 'history'
                  ? 'bg-indigo-50 text-indigo-700 font-semibold'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              History
            </button>
          </nav>
        </div>

        <div className="flex items-center space-x-4">
          {/* Health probe badge */}
          <span
            aria-live="polite"
            role="status"
            className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
              health === 'connected'
                ? 'bg-green-100 text-green-800'
                : health === 'loading'
                ? 'bg-blue-100 text-blue-800'
                : health === 'degraded'
                ? 'bg-yellow-100 text-yellow-800'
                : 'bg-red-100 text-red-800'
            }`}
          >
            <span
              className={`w-2 h-2 mr-1.5 rounded-full ${
                health === 'connected'
                  ? 'bg-green-500'
                  : health === 'loading'
                  ? 'bg-blue-500'
                  : health === 'degraded'
                  ? 'bg-yellow-500'
                  : 'bg-red-500'
              }`}
            />
            {health === 'connected' && `API Connected (${metadataStatus})`}
            {health === 'loading' && 'Checking API...'}
            {health === 'degraded' && 'API Degraded'}
            {health === 'offline' && 'API Offline'}
          </span>

          <div className="flex items-center space-x-2 text-xs">
            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
              Admin (Local Mode)
            </span>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {/* Welcome Banner */}
        <section aria-labelledby="welcome-heading" className="bg-white rounded-lg shadow-sm border border-slate-200 p-6">
          <h2 id="welcome-heading" className="text-xl font-bold text-slate-900 mb-1">
            Natural-Language Analytics for PostgreSQL and MySQL
          </h2>
          <p className="text-sm text-slate-600">
            QueryLens translates natural language questions into safe, read-only SQL with bounded execution, transparent assumptions, and verified accuracy.
          </p>
        </section>

        {/* Tab View */}
        {activeTab === 'ask' && (
          health === 'connected' ? (
            <WorkspaceView onNavigateToConnections={() => setActiveTab('connections')} />
          ) : (
            <div className="bg-white rounded-lg border border-slate-200 p-8 text-center space-y-4">
              <h3 className="text-base font-semibold text-slate-800">
                {health === 'loading' ? 'Connecting to QueryLens API...' : 'Backend API Server is Offline'}
              </h3>
              <p className="text-sm text-slate-500 max-w-lg mx-auto">
                {health === 'loading'
                  ? 'Checking server status on http://127.0.0.1:8000...'
                  : 'Click reconnect below or refresh the page to reconnect to the live API server.'}
              </p>
              <button
                onClick={checkHealth}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-sm font-medium transition shadow-sm"
              >
                Reconnect to API
              </button>
            </div>
          )
        )}

        {activeTab === 'connections' && (
          <div className="space-y-6">
            <ConnectionManager />
          </div>
        )}

        {activeTab === 'schema' && (
          <div className="space-y-6">
            <SchemaExplorer
              connectionId={selectedConnectionId}
              onConnectionChange={setSelectedConnectionId}
            />
          </div>
        )}

        {activeTab === 'history' && (
          <div className="space-y-6">
            <History onSelectRun={() => setActiveTab('ask')} />
          </div>
        )}


      </main>

      <footer className="border-t border-slate-200 bg-white py-4 px-6 text-center text-xs text-slate-500">
        QueryLens &bull; Production-grade AI SQL Workspace
      </footer>
    </div>
  );
}

export default App;
