import React from 'react';

export interface UserSession {
  id: string;
  email: string;
  role: string;
}

export interface AppShellProps {
  currentRoute: string;
  onRouteChange: (route: string) => void;
  user: UserSession | null;
  onLogout: () => void;
  children: React.ReactNode;
}

export function AppShell({
  currentRoute,
  onRouteChange,
  user,
  onLogout,
  children,
}: AppShellProps): React.JSX.Element {
  const navItems = [
    { id: 'connections', label: 'Connections' },
    { id: 'schema', label: 'Explore Schema' },
    { id: 'ask', label: 'Ask Data' },
    { id: 'history', label: 'History' },
    { id: 'diagnostics', label: 'Diagnostics' },
  ];

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="bg-slate-900 text-white border-b border-slate-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-8">
            <div className="flex items-center space-x-3">
              <span className="text-indigo-400 font-bold text-xl tracking-tight">QueryLens</span>
              <span className="px-2 py-0.5 text-xs bg-slate-800 text-slate-300 rounded border border-slate-700">
                MVP
              </span>
            </div>

            <nav className="flex space-x-1" aria-label="Main Navigation">
              {navItems.map((item) => {
                const isActive = currentRoute === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => onRouteChange(item.id)}
                    className={`px-3 py-2 rounded-md text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-400 ${
                      isActive
                        ? 'bg-slate-800 text-indigo-400 font-semibold'
                        : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                    }`}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    {item.label}
                  </button>
                );
              })}
            </nav>
          </div>

          <div className="flex items-center space-x-4">
            {user ? (
              <div className="flex items-center space-x-3 text-sm">
                <span className="text-slate-300 text-xs font-mono">{user.email}</span>
                <button
                  onClick={onLogout}
                  className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded text-xs font-medium text-slate-200 focus:outline-none focus:ring-2 focus:ring-rose-500"
                >
                  Logout
                </button>
              </div>
            ) : (
              <span className="text-xs text-slate-400">Not authenticated</span>
            )}
          </div>
        </div>
      </header>

      {/* Main Content Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {children}
      </main>
    </div>
  );
}

export default AppShell;
