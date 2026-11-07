import React, { useEffect, useState } from 'react';

export type HealthStatus = 'loading' | 'connected' | 'offline' | 'degraded';

export function App(): React.JSX.Element {
  const [health, setHealth] = useState<HealthStatus>('loading');
  const [metadataStatus, setMetadataStatus] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    fetch('/api/v1/health')
      .then(async (res) => {
        if (!isMounted) return;
        if (res.ok) {
          const data = await res.json();
          setHealth('connected');
          setMetadataStatus(data.metadata_db || 'healthy');
        } else {
          setHealth('degraded');
          setMetadataStatus('unreachable');
        }
      })
      .catch((_err) => {
        if (isMounted) {
          setHealth('offline');
          setMetadataStatus(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-800">
      <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded bg-indigo-600 flex items-center justify-center text-white font-bold text-lg">
            Q
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">QueryLens</h1>
        </div>
        <nav aria-label="Main Navigation" className="flex items-center space-x-4">
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
        </nav>
      </header>

      <main className="flex-1 max-w-7xl w-full mx-auto p-6">
        <section aria-labelledby="welcome-heading" className="bg-white rounded-lg shadow-sm border border-slate-200 p-8">
          <h2 id="welcome-heading" className="text-2xl font-bold text-slate-900 mb-2">
            Natural-Language Analytics for PostgreSQL and MySQL
          </h2>
          <p className="text-slate-600 mb-6">
            QueryLens translates natural language questions into safe, read-only SQL with bounded execution, transparent assumptions, and verified accuracy.
          </p>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white py-4 px-6 text-center text-xs text-slate-500">
        QueryLens &bull; Production-grade AI SQL Workspace
      </footer>
    </div>
  );
}

export default App;
