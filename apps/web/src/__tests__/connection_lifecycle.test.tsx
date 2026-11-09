import { StrictMode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SchemaExplorer } from '../features/schema/SchemaExplorer.tsx';
import { WorkspaceView } from '../features/workspace/WorkspaceView.tsx';

const replacement = { id: 'replacement', name: 'New database', engine: 'postgresql' };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

afterEach(() => { vi.unstubAllGlobals(); });

it('resolves a deleted schema selection before requesting connection metadata', async () => {
  const changed = vi.fn();
  const fetch = vi.fn(async (url: string) => {
    if (url === '/api/v1/connections') return response([replacement]);
    if (url.endsWith('/schema')) return response({
      connection_id: replacement.id, snapshot_hash: 'abc', policy_version: 1, tables: [],
    });
    if (url.endsWith('/labels')) return response({ semantic_version: 1, labels: [] });
    return response([]);
  });
  vi.stubGlobal('fetch', fetch);
  render(<StrictMode><SchemaExplorer connectionId="deleted" onConnectionChange={changed} /></StrictMode>);
  await waitFor(() => expect(screen.getByLabelText('Schema database')).toHaveValue('replacement'));
  expect(await screen.findByText(/Select allowed tables/)).toBeInTheDocument();
  expect(fetch.mock.calls.every(([url]) => !url.includes('/deleted/'))).toBe(true);
  expect(changed).toHaveBeenCalledWith('replacement');
});

it('recovers from a removed query without locking the new connection selector', async () => {
  const changed = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/v1/connections'
    ? response([replacement])
    : response({ error: { code: 'NOT_FOUND', message: 'Query run not found' } }, 404)));
  render(<WorkspaceView initialQueryId="deleted-run" onActiveQueryChange={changed} onNavigateToConnections={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('This query is no longer available');
  expect(screen.getByLabelText('Database Source')).toBeEnabled();
  expect(screen.getByLabelText('Database Source')).toHaveValue('replacement');
  expect(screen.queryByText('Queued')).not.toBeInTheDocument();
  expect(changed).toHaveBeenCalledWith(null);
});

it('keeps one labels panel and one metrics panel after refreshing the schema', async () => {
  const catalog = { connection_id: replacement.id, snapshot_hash: 'abc', policy_version: 1, tables: [] };
  const fetch = vi.fn(async (url: string) => {
    if (url === '/api/v1/connections') return response([replacement]);
    if (url.endsWith('/schema') || url.endsWith('/refresh')) return response(catalog);
    if (url.endsWith('/labels')) return response({ semantic_version: 1, labels: [] });
    return response([]);
  });
  vi.stubGlobal('fetch', fetch);
  render(<StrictMode><SchemaExplorer connectionId="replacement" /></StrictMode>);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save labels' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Refresh schema' }));
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/refresh'))).toBe(true));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save labels' })).toBeEnabled());
  expect(screen.getAllByRole('heading', { name: 'Business labels' })).toHaveLength(1);
  expect(screen.getAllByRole('heading', { name: 'Business metrics' })).toHaveLength(1);
});
