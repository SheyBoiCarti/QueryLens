import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../api/client.ts';
import ConnectionManager from '../features/connections/ConnectionManager.tsx';
import { VisibilityEditor } from '../features/connections/VisibilityEditor.tsx';
import { ConnectionResponse } from '../api/generated/schema.ts';

vi.mock('../api/client.ts', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() }, ApiError: class extends Error {} }));

const connection: ConnectionResponse = {
  id: 'db', user_id: 'owner', name: 'Analytics', engine: 'postgresql',
  host: 'db.example.test', port: 5432, database: 'analytics', username: 'reader',
  tls_enabled: true, allowed_tables: { 'public.customers': ['id'] }, created_at: '', updated_at: '',
};

beforeEach(() => { vi.resetAllMocks(); });

it('imports on save and returns to the list without requiring table selection', async () => {
  vi.mocked(api.get).mockResolvedValue([]);
  vi.mocked(api.post).mockResolvedValue(connection);
  render(<ConnectionManager />);
  fireEvent.click(await screen.findByText('Add Connection'));
  fireEvent.change(screen.getByLabelText('Connection link'), { target: { value: 'postgres://reader:pass@db.example.test/analytics?sslmode=require' } });
  fireEvent.click(screen.getByText('Use connection link'));
  fireEvent.change(screen.getByLabelText('Connection Name'), { target: { value: 'Analytics' } });
  vi.mocked(api.get).mockResolvedValue([connection]);
  fireEvent.click(screen.getByText('Save Connection'));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/v1/connections', expect.objectContaining({ import_schema: true })));
  expect(await screen.findByText('Select tables')).toBeInTheDocument();
  expect(screen.queryByText(/Select tables and columns for/)).not.toBeInTheDocument();
});

it('blocks saving after failed discovery and allows retry', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('Could not read the database schema.'))
    .mockResolvedValueOnce({ 'public.customers': ['id', 'name'] });
  render(<VisibilityEditor connection={connection} onDone={vi.fn()} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not read');
  expect(screen.getByText('Save selections')).toBeDisabled();
  expect(screen.queryByText('No selectable tables were found.')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Retry discovery'));
  expect(await screen.findByText('public.customers')).toBeInTheDocument();
  expect(screen.getByText('Save selections')).toBeEnabled();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
