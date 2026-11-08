import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { WorkspaceView } from '../features/workspace/WorkspaceView.tsx';
import { PublicRunCompleted, PublicRunFailed } from '../api/generated/schema.ts';

const connectionItem = { id: 'conn-1', name: 'Main DB', engine: 'postgresql', host: 'localhost', port: 5432, database: 'db', username: 'u' };
const otherConnection = { id: 'conn-2', name: 'Secondary DB', engine: 'postgresql', host: 'localhost', port: 5432, database: 'db2', username: 'u' };

const initialCompletedRun: PublicRunCompleted = {
  query_id: 'run-init',
  connection_id: 'conn-1',
  status: 'completed',
  state_version: 1,
  question: 'Initial query',
  created_at: '2026-11-08T12:00:00Z',
  updated_at: '2026-11-08T12:00:05Z',
  dialect: 'postgresql',
  sql: 'SELECT id, email FROM customers;',
  assumptions: [],
  warnings: [],
  columns: [
    { name: 'id', type: 'integer', db_type: 'integer' },
    { name: 'email', type: 'string', db_type: 'text' },
  ],
  row_count: 1,
  truncated: false,
  results_available: true,
  results_expires_at: new Date(Date.now() + 3600000).toISOString(),
  rows: [{ id: 1, email: 'alice@example.com' }],
  presentation: {
    title: 'Customer List',
    explanation: '1 returned row.',
    chart_type: 'table',
  },
};

const editedRunAccepted: PublicRunCompleted = {
  query_id: 'run-manual',
  connection_id: 'conn-1',
  status: 'completed',
  state_version: 2,
  question: 'Initial query',
  created_at: '2026-11-08T12:01:00Z',
  updated_at: '2026-11-08T12:01:05Z',
  origin: 'manual_sql',
  source_query_id: 'run-init',
  dialect: 'postgresql',
  sql: 'SELECT id, email, created_at FROM customers LIMIT 100;',
  assumptions: [],
  warnings: [],
  columns: [
    { name: 'id', type: 'integer', db_type: 'integer' },
    { name: 'email', type: 'string', db_type: 'text' },
    { name: 'created_at', type: 'datetime', db_type: 'timestamp' },
  ],
  row_count: 1,
  truncated: false,
  results_available: true,
  results_expires_at: new Date(Date.now() + 3600000).toISOString(),
  rows: [{ id: 1, email: 'alice@example.com', created_at: '2026-01-01T00:00:00Z' }],
  presentation: {
    title: 'Customer List',
    explanation: '1 returned row.',
    chart_type: 'table',
  },
};

describe('Workspace Selection State and Manual SQL Execution (Task 10)', () => {
  let fetchMock: any;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('submits manual SQL to /api/v1/queries/sql with exact connection, source, max_rows, and displays accepted run', async () => {
    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem, otherConnection]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/sql') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        expect(body.connection_id).toBe('conn-1');
        expect(body.source_query_id).toBe('run-init');
        expect(body.sql).toBe('SELECT id, email, created_at FROM customers LIMIT 100;');
        expect(body.max_rows).toBe(100);
        return new Response(JSON.stringify({ query_id: 'run-manual', status: 'queued' }), { status: 202, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-manual')) {
        return new Response(JSON.stringify(editedRunAccepted), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-init')) {
        return new Response(JSON.stringify(initialCompletedRun), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-init" />);

    // Initial query loads
    expect(await screen.findByText('SELECT id, email FROM customers;')).toBeInTheDocument();

    // Open editor
    fireEvent.click(screen.getByRole('button', { name: /edit sql/i }));
    const textarea = screen.getByRole('textbox', { name: /sql editor/i });
    fireEvent.change(textarea, { target: { value: 'SELECT id, email, created_at FROM customers LIMIT 100;' } });

    // Click Run Edited SQL
    fireEvent.click(screen.getByRole('button', { name: /run edited sql/i }));

    // Polls and displays the accepted run
    await waitFor(() => {
      expect(screen.getByText('SELECT id, email, created_at FROM customers LIMIT 100;')).toBeInTheDocument();
    });
  });

  it('prompts dirty-draft confirmation when switching connections and aborts if rejected', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem, otherConnection]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-init')) {
        return new Response(JSON.stringify(initialCompletedRun), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-init" />);

    expect(await screen.findByText('SELECT id, email FROM customers;')).toBeInTheDocument();

    // Edit SQL
    fireEvent.click(screen.getByRole('button', { name: /edit sql/i }));
    const textarea = screen.getByRole('textbox', { name: /sql editor/i });
    fireEvent.change(textarea, { target: { value: 'SELECT changed FROM customers;' } });

    // Switch connection
    const connSelect = screen.getByLabelText(/database source/i);
    fireEvent.change(connSelect, { target: { value: 'conn-2' } });

    expect(confirmSpy).toHaveBeenCalled();
    // Since user rejected discard, connection should NOT switch
    expect(connSelect).toHaveValue('conn-1');
  });

  it('leaves prior successful answer selectable when manual execution fails', async () => {
    const failedRun: PublicRunFailed = {
      query_id: 'run-fail',
      connection_id: 'conn-1',
      status: 'failed',
      state_version: 2,
      question: 'Initial query',
      created_at: '2026-11-08T12:02:00Z',
      updated_at: '2026-11-08T12:02:05Z',
      origin: 'manual_sql',
      source_query_id: 'run-init',
      error_code: 'SYNTAX_ERROR',
      safe_message: 'Syntax error near FROMM',
    };

    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/sql') && options.method === 'POST') {
        return new Response(JSON.stringify({ query_id: 'run-fail', status: 'queued' }), { status: 202, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-fail')) {
        return new Response(JSON.stringify(failedRun), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-init')) {
        return new Response(JSON.stringify(initialCompletedRun), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-init" />);

    expect(await screen.findByText('SELECT id, email FROM customers;')).toBeInTheDocument();

    // Edit and run failed SQL
    fireEvent.click(screen.getByRole('button', { name: /edit sql/i }));
    const textarea = screen.getByRole('textbox', { name: /sql editor/i });
    fireEvent.change(textarea, { target: { value: 'SELECT * FROMM customers;' } });
    fireEvent.click(screen.getByRole('button', { name: /run edited sql/i }));

    // Error is shown
    expect(await screen.findByText('Syntax error near FROMM')).toBeInTheDocument();

    // Prior successful run is selectable
    const returnToPriorBtn = screen.getByRole('button', { name: /view previous successful answer/i });
    fireEvent.click(returnToPriorBtn);

    // Initial successful answer is shown again
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
  });
});
