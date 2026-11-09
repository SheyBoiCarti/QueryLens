import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { WorkspaceView } from '../features/workspace/WorkspaceView.tsx';
import { PublicRunCompleted, PublicRunFailed } from '../api/generated/schema.ts';

const connectionItem = { id: 'conn-1', name: 'Main DB', engine: 'postgresql', host: 'localhost', port: 5432, database: 'db', username: 'u' };
const otherConnection = { id: 'conn-2', name: 'Analytics DB', engine: 'postgresql', host: 'localhost', port: 5432, database: 'db2', username: 'u' };

const runA: PublicRunCompleted = {
  query_id: 'run-A',
  connection_id: 'conn-1',
  status: 'completed',
  state_version: 1,
  question: 'Show all customers in USA',
  created_at: '2026-11-08T12:00:00Z',
  updated_at: '2026-11-08T12:00:05Z',
  dialect: 'postgresql',
  sql: "SELECT id, name FROM customers WHERE country = 'USA';",
  assumptions: [],
  warnings: [],
  columns: [
    { name: 'id', type: 'integer', db_type: 'integer' },
    { name: 'name', type: 'string', db_type: 'text' },
  ],
  row_count: 2,
  truncated: false,
  results_available: true,
  results_expires_at: new Date(Date.now() + 3600000).toISOString(),
  rows: [{ id: 1, name: 'Alice' }, { id: 2, name: 'Bob' }],
  context: {
    effective_question: 'Show all customers in USA',
    canonical_sql_template: "SELECT id, name FROM customers WHERE country = 'USA';",
    snapshot_hash: 'hash-1',
    policy_version: 1,
    semantic_version: 1,
    referenced_objects: [
      { namespace: 'public', table_name: 'customers', column_name: 'country' },
    ],
  },
  presentation: {
    title: 'USA Customers',
    explanation: '2 returned rows.',
    chart_type: 'table',
  },
};

const runB: PublicRunCompleted = {
  query_id: 'run-B',
  connection_id: 'conn-1',
  status: 'completed',
  state_version: 1,
  origin: 'follow_up',
  parent_query_id: 'run-A',
  question: 'Only with ID > 1',
  created_at: '2026-11-08T12:01:00Z',
  updated_at: '2026-11-08T12:01:05Z',
  dialect: 'postgresql',
  sql: "SELECT id, name FROM customers WHERE country = 'USA' AND id > 1;",
  assumptions: [],
  warnings: [],
  columns: [
    { name: 'id', type: 'integer', db_type: 'integer' },
    { name: 'name', type: 'string', db_type: 'text' },
  ],
  row_count: 1,
  truncated: false,
  results_available: true,
  results_expires_at: new Date(Date.now() + 3600000).toISOString(),
  rows: [{ id: 2, name: 'Bob' }],
  presentation: {
    title: 'USA Customers with ID > 1',
    explanation: '1 returned row.',
    chart_type: 'table',
  },
};

describe('Follow-Up Selection, Branching, and Failure Recovery (Task 12)', () => {
  let fetchMock: any;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('branches from selected parent: completes A, completes B, selects A, submits C with A parent_query_id', async () => {
    const postCalls: any[] = [];

    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        postCalls.push(body);
        const queryId = body.parent_query_id === 'run-A' && body.question === 'Only with ID > 1' ? 'run-B' : 'run-C';
        return new Response(JSON.stringify({ query_id: queryId, status: 'queued' }), { status: 202, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-A')) {
        return new Response(JSON.stringify(runA), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-B')) {
        return new Response(JSON.stringify(runB), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-C')) {
        return new Response(
          JSON.stringify({
            ...runA,
            query_id: 'run-C',
            parent_query_id: 'run-A',
            question: 'Order by name desc',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    function TestApp() {
      const [currentId, setCurrentId] = useState<string | null>('run-A');
      return (
        <div>
          <button onClick={() => setCurrentId('run-A')}>Select Run A</button>
          <WorkspaceView
            onNavigateToConnections={vi.fn()}
            initialQueryId={currentId}
            onActiveQueryChange={setCurrentId}
          />
        </div>
      );
    }

    render(<TestApp />);

    // 1. Initial query A loads
    expect(await screen.findByText('Show all customers in USA')).toBeInTheDocument();
    expect(screen.getByText('Following up on: "Show all customers in USA"')).toBeInTheDocument();

    // 2. Submit follow-up B
    const followupInput = screen.getByPlaceholderText(/ask a follow-up question/i);
    fireEvent.change(followupInput, { target: { value: 'Only with ID > 1' } });
    fireEvent.click(screen.getByRole('button', { name: /ask follow-up/i }));

    await waitFor(() => {
      expect(postCalls.length).toBe(1);
      expect(postCalls[0].parent_query_id).toBe('run-A');
    });

    // 3. Query B completed
    expect(await screen.findByText('Only with ID > 1')).toBeInTheDocument();

    // 4. Now select A again (simulating history inspection of run-A)
    fireEvent.click(screen.getByRole('button', { name: 'Select Run A' }));
    expect(await screen.findByText('Following up on: "Show all customers in USA"')).toBeInTheDocument();

    // 5. Submit follow-up C from selected A
    const followupInputC = screen.getByPlaceholderText(/ask a follow-up question/i);
    fireEvent.change(followupInputC, { target: { value: 'Order by name desc' } });
    fireEvent.click(screen.getByRole('button', { name: /ask follow-up/i }));

    // C must have parent_query_id: 'run-A', NOT 'run-B'!
    await waitFor(() => {
      expect(postCalls.length).toBe(2);
      expect(postCalls[1].parent_query_id).toBe('run-A');
    });
  });

  it('fails follow-up B and retains successful parent A selectable', async () => {
    const failedRunB: PublicRunFailed = {
      query_id: 'run-B-fail',
      connection_id: 'conn-1',
      status: 'failed',
      state_version: 2,
      origin: 'follow_up',
      parent_query_id: 'run-A',
      question: 'Bad follow-up',
      created_at: '2026-11-08T12:02:00Z',
      updated_at: '2026-11-08T12:02:05Z',
      error_code: 'POLICY_VIOLATION',
      safe_message: 'Prohibited function in follow-up',
    };

    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries') && options.method === 'POST') {
        return new Response(JSON.stringify({ query_id: 'run-B-fail', status: 'queued' }), { status: 202, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-B-fail')) {
        return new Response(JSON.stringify(failedRunB), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-A')) {
        return new Response(JSON.stringify(runA), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-A" />);

    expect(await screen.findByText('Show all customers in USA')).toBeInTheDocument();

    // Submit failing follow-up
    const followupInput = screen.getByPlaceholderText(/ask a follow-up question/i);
    fireEvent.change(followupInput, { target: { value: 'Bad follow-up' } });
    fireEvent.click(screen.getByRole('button', { name: /ask follow-up/i }));

    // B fails
    expect(await screen.findByText('Prohibited function in follow-up')).toBeInTheDocument();

    // Prior successful parent A is retained selectable
    const returnToPrior = screen.getByRole('button', { name: /view previous successful answer/i });
    fireEvent.click(returnToPrior);

    // Parent A is displayed
    expect(await screen.findByText('Show all customers in USA')).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });

  it('Start new question button clears parent and resets follow-up bar', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-A')) {
        return new Response(JSON.stringify(runA), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-A" />);

    expect(await screen.findByText('Following up on: "Show all customers in USA"')).toBeInTheDocument();

    // Click Start new question
    fireEvent.click(screen.getByRole('button', { name: /start new question/i }));

    // Follow-up bar is cleared, workspace returns to clean state
    expect(screen.queryByText(/following up on:/i)).toBeNull();
  });

  it('offers explicit action to ask as standalone question on 409 stale follow-up context', async () => {
    const postCalls: any[] = [];

    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        postCalls.push(body);
        if (body.parent_query_id) {
          // Reject with 409 FOLLOWUP_CONTEXT_STALE
          return new Response(
            JSON.stringify({
              detail: {
                error_code: 'FOLLOWUP_CONTEXT_STALE',
                message: 'Catalog snapshot changed since parent query was run',
              },
            }),
            { status: 409, headers: { 'Content-Type': 'application/json' } }
          );
        }
        return new Response(JSON.stringify({ query_id: 'run-standalone', status: 'queued' }), { status: 202, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-A')) {
        return new Response(JSON.stringify(runA), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-A" />);

    expect(await screen.findByText('Show all customers in USA')).toBeInTheDocument();

    // Submit follow-up that encounters stale drift
    const followupInput = screen.getByPlaceholderText(/ask a follow-up question/i);
    fireEvent.change(followupInput, { target: { value: 'Customer count' } });
    fireEvent.click(screen.getByRole('button', { name: /ask follow-up/i }));

    // Stale notice and standalone action
    expect(await screen.findByText(/catalog snapshot changed/i)).toBeInTheDocument();
    const standaloneBtn = screen.getByRole('button', { name: /ask as a standalone question/i });
    fireEvent.click(standaloneBtn);

    // Submits without parent_query_id
    await waitFor(() => {
      expect(postCalls.length).toBe(2);
      expect(postCalls[1].parent_query_id).toBeUndefined();
      expect(postCalls[1].question).toBe('Customer count');
    });
  });

  it('allows follow-up when parent results have expired but context is retained', async () => {
    const expiredRunA: PublicRunCompleted = {
      ...runA,
      results_available: false,
      rows: undefined,
    };

    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-A')) {
        return new Response(JSON.stringify(expiredRunA), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-A" />);

    expect(await screen.findByText('Show all customers in USA')).toBeInTheDocument();
    // Follow-up bar is available even if volatile results expired
    expect(screen.getByText('Following up on: "Show all customers in USA"')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask a follow-up question/i)).toBeInTheDocument();
  });

  it('connection change clears selected parent context', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem, otherConnection]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/run-A')) {
        return new Response(JSON.stringify(runA), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="run-A" />);

    expect(await screen.findByText('Following up on: "Show all customers in USA"')).toBeInTheDocument();

    // Change connection via select
    const select = screen.getByLabelText(/database source/i);
    fireEvent.change(select, { target: { value: 'conn-2' } });

    // Follow-up bar is cleared on connection switch
    expect(screen.queryByText(/following up on:/i)).toBeNull();
  });
});
