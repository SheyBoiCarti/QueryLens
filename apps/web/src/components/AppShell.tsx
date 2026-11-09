import React, { createContext, useContext, useEffect, useState } from 'react';
import { Search, Database, Table2, MessageSquare, History } from 'lucide-react';

interface DatabaseContext { database?: string; namespace?: string }
const BreadcrumbContext = createContext<(context: DatabaseContext) => void>(() => {});

export function useDatabaseBreadcrumb(database?: string, namespace?: string): void {
  const update = useContext(BreadcrumbContext);
  useEffect(() => { update({ database, namespace }); }, [database, namespace, update]);
}

export interface AppShellProps {
  currentRoute: string;
  onRouteChange: (route: string) => void;
  children: React.ReactNode;
}

export function AppShell({ currentRoute, onRouteChange, children }: AppShellProps): React.JSX.Element {
  const [{ database, namespace }, setDatabaseContext] = useState<DatabaseContext>({});
  const navItems = [
    { id: 'connections', label: 'Connections', icon: Database },
    { id: 'schema', label: 'Explore schema', icon: Table2 },
    { id: 'ask', label: 'Ask data', icon: MessageSquare },
    { id: 'history', label: 'History', icon: History },
  ];

  return (
    <div className="min-h-screen bg-page font-sans">
      <header className="app-topbar">
        <Search size={18} strokeWidth={1.8} className="text-accent" aria-hidden="true" />
        <span className="app-brand">QueryLens</span>
        {database && <div className="app-breadcrumb" aria-label="Current database">
          <span aria-hidden="true">/</span><span className="text-text">{database}</span>
          {namespace && <><span aria-hidden="true">/</span><span>{namespace}</span></>}
        </div>}
      </header>
      <div className="app-layout">
        <aside className="app-sidebar">
          <p className="workspace-label">Workspace</p>
          <nav className="app-nav" aria-label="Main navigation">
            {navItems.map(({ id, label, icon: Icon }) => (
              <button key={id} type="button" onClick={() => onRouteChange(id)} aria-current={currentRoute === id ? 'page' : undefined}>
                <Icon size={16} strokeWidth={1.7} aria-hidden="true" />{label}
              </button>
            ))}
          </nav>
        </aside>
        <main className="app-main"><div className="app-content"><BreadcrumbContext.Provider value={setDatabaseContext}>{children}</BreadcrumbContext.Provider></div></main>
      </div>
    </div>
  );
}

export default AppShell;
