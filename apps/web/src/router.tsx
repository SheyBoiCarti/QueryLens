import { useState, useEffect } from 'react';

export type AppRoute = 'connections' | 'schema' | 'ask' | 'history';

export function useRouter() {
  const [route, setRoute] = useState<AppRoute>(() => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'diagnostics') return 'ask';
    if (['connections', 'schema', 'ask', 'history'].includes(hash)) {
      return hash as AppRoute;
    }
    return 'ask';
  });

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '');
      if (hash === 'diagnostics') { setRoute('ask'); return; }
      if (['connections', 'schema', 'ask', 'history'].includes(hash)) {
        setRoute(hash as AppRoute);
      }
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const navigate = (nextRoute: AppRoute) => {
    window.location.hash = nextRoute;
    setRoute(nextRoute);
  };

  return { route, navigate };
}
