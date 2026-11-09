import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SavedQuestionsModal } from '../features/workspace/SavedQuestionsModal.tsx';
import { SavedQuestionsManager } from '../features/workspace/SavedQuestionsManager.tsx';
import { SavedQuestionFilters } from '../features/workspace/SavedQuestionFilters.tsx';
import { ParameterDefinition, SavedQuestionDetail } from '../api/generated/schema.ts';

const sampleDefinitions: ParameterDefinition[] = [
  {
    slot_id: 'slot-country',
    name: 'country',
    label: 'Customer Country',
    param_type: 'category',
    source_type: 'string',
    target: {
      scope: 'root',
      predicate_path: 'where.0',
      namespace: 'public',
      table_name: 'customers',
      column_name: 'country',
      operator: '=',
    },
    allowed_values: ['USA', 'UK', 'Canada'],
    default_value: 'USA',
  },
  {
    slot_id: 'slot-dates',
    name: 'order_date',
    label: 'Order Date Range',
    param_type: 'date_range',
    source_type: 'date',
    target: {
      scope: 'root',
      predicate_path: 'where.1',
      namespace: 'public',
      table_name: 'orders',
      column_name: 'order_date',
      operator: 'BETWEEN',
    },
    default_value: { mode: 'this_month' },
  },
  {
    slot_id: 'slot-count',
    name: 'result_count',
    label: 'Result Limit',
    param_type: 'result_count',
    source_type: 'integer',
    default_value: 100,
  },
];

const sampleDetail: SavedQuestionDetail = {
  id: 'saved-1',
  connection_id: 'conn-1',
  title: 'Active Customers by Country',
  description: 'Monthly overview of active customers',
  chart_preference: 'bar',
  default_max_rows: 100,
  revision: 2,
  created_at: '2026-11-08T10:00:00Z',
  updated_at: '2026-11-08T10:30:00Z',
  canonical_sql_template: 'SELECT id FROM public.customers WHERE country = %(country)s LIMIT %(result_count)s;',
  effective_question: 'Active customers in country',
  parameters: sampleDefinitions,
  referenced_objects: [
    { namespace: 'public', table_name: 'customers', column_name: 'country' },
  ],
  metric_references: [],
};

describe('Saved questions Modal (Task 11)', () => {
  let fetchMock: any;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('fetches server-discovered slots and saves question with typed configuration', async () => {
    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/queries/q-1/parameters')) {
        return new Response(
          JSON.stringify({
            template_fingerprint: 'fp-123',
            definitions: sampleDefinitions,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      if (url.includes('/api/v1/saved-questions') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        expect(body.source_query_id).toBe('q-1');
        expect(body.title).toBe('Monthly Customers');
        expect(body.parameters).toBeDefined();
        return new Response(JSON.stringify(sampleDetail), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    const onSaved = vi.fn();
    const onClose = vi.fn();

    render(<SavedQuestionsModal sourceQueryId="q-1" onClose={onClose} onSaved={onSaved} />);

    // Waits for slots discovery
    expect(await screen.findByDisplayValue('Customer Country')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Order Date Range')).toBeInTheDocument();
    expect(screen.getByText(/inclusive end-date UTC/i)).toBeInTheDocument();

    // Fill title
    const titleInput = screen.getByLabelText(/title/i);
    fireEvent.change(titleInput, { target: { value: 'Monthly Customers' } });

    // Submit
    fireEvent.click(screen.getByRole('button', { name: /save question/i }));

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(sampleDetail);
      expect(onClose).toHaveBeenCalled();
    });
  });
});

describe('SavedQuestionFilters (Task 11)', () => {
  it('renders typed inputs and date presets without stringifying numeric/bool values', () => {
    const values: Record<string, any> = {
      country: 'USA',
      order_date: { mode: 'this_month' },
      result_count: 50,
    };
    const onChange = vi.fn();
    const onRun = vi.fn();

    render(
      <SavedQuestionFilters
        parameters={sampleDefinitions}
        values={values}
        onChange={onChange}
        onRun={onRun}
      />
    );

    // Category select
    const countrySelect = screen.getByLabelText('Customer Country');
    expect(countrySelect).toHaveValue('USA');
    fireEvent.change(countrySelect, { target: { value: 'UK' } });
    expect(onChange).toHaveBeenCalledWith('country', 'UK');

    // Date range preset select
    const datePreset = screen.getByLabelText(/order date range preset/i);
    expect(datePreset).toHaveValue('this_month');
    fireEvent.change(datePreset, { target: { value: 'this_year' } });
    expect(onChange).toHaveBeenCalledWith('order_date', { mode: 'this_year' });

    // Number input
    const countInput = screen.getByLabelText('Result Limit');
    expect(countInput).toHaveValue(50);
    fireEvent.change(countInput, { target: { value: '200' } });
    expect(onChange).toHaveBeenCalledWith('result_count', 200);

    // Run button
    fireEvent.click(screen.getByRole('button', { name: /run with filters/i }));
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});

describe('SavedQuestionsManager (Task 11)', () => {
  let fetchMock: any;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('lists saved questions, runs with typed filters, and triggers onRunAccepted', async () => {
    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/saved-questions?connection_id=conn-1')) {
        return new Response(
          JSON.stringify({
            items: [
              {
                id: 'saved-1',
                connection_id: 'conn-1',
                title: 'Active Customers by Country',
                description: 'Overview',
                default_max_rows: 100,
                revision: 2,
                created_at: '2026-11-08T10:00:00Z',
                updated_at: '2026-11-08T10:30:00Z',
              },
            ],
            next_cursor: null,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      if (url.includes('/api/v1/saved-questions/saved-1/run') && options.method === 'POST') {
        const body = JSON.parse(options.body);
        expect(body.expected_revision).toBe(2);
        expect(body.parameters).toBeDefined();
        return new Response(JSON.stringify({ query_id: 'new-run-99', status: 'accepted' }), {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.includes('/api/v1/saved-questions/saved-1')) {
        return new Response(JSON.stringify(sampleDetail), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    const onRunAccepted = vi.fn();

    render(<SavedQuestionsManager connectionId="conn-1" onRunAccepted={onRunAccepted} />);

    // Item listed
    expect(await screen.findByText('Active Customers by Country')).toBeInTheDocument();

    // Select to view detail and filters
    fireEvent.click(screen.getByRole('button', { name: /view or run/i }));

    // Run button inside filters
    const runBtn = await screen.findByRole('button', { name: /run with filters/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(onRunAccepted).toHaveBeenCalledWith('new-run-99');
    });
  });

  it('handles review-required error on run when dependencies drift', async () => {
    fetchMock.mockImplementation(async (url: string, options: any = {}) => {
      if (url.includes('/api/v1/saved-questions?connection_id=conn-1')) {
        return new Response(
          JSON.stringify({ items: [sampleDetail], next_cursor: null }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      if (url.includes('/api/v1/saved-questions/saved-1/run') && options.method === 'POST') {
        return new Response(
          JSON.stringify({
            detail: {
              error_code: 'REVIEW_REQUIRED',
              message: 'Table public.customers was modified; review required',
            },
          }),
          { status: 409, headers: { 'Content-Type': 'application/json' } }
        );
      }
      if (url.includes('/api/v1/saved-questions/saved-1')) {
        return new Response(JSON.stringify(sampleDetail), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<SavedQuestionsManager connectionId="conn-1" onRunAccepted={vi.fn()} />);

    expect(await screen.findByText('Active Customers by Country')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /view or run/i }));

    const runBtn = await screen.findByRole('button', { name: /run with filters/i });
    fireEvent.click(runBtn);

    expect(await screen.findByText(/table public\.customers was modified; review required/i)).toBeInTheDocument();
  });
});

describe('Saved question review regressions', () => {
  afterEach(() => { vi.unstubAllGlobals(); });
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

  it('authors a subset of slots with typed defaults and category choices over HTTP', async () => {
    let savedBody: any;
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit = {}) => {
      if (options.method === 'POST') {
        savedBody = JSON.parse(String(options.body));
        return json(sampleDetail, 201);
      }
      return json({ definitions: sampleDefinitions, template_fingerprint: 'fp' });
    }));
    const close = vi.fn();
    render(<SavedQuestionsModal sourceQueryId="q-1" onClose={close} />);
    await screen.findByDisplayValue('Customer Country');
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Authored' } });
    fireEvent.click(screen.getByLabelText('Expose order_date filter'));
    fireEvent.change(screen.getByLabelText('country allowed choices'), { target: { value: 'USA\nUK' } });
    fireEvent.change(screen.getByLabelText('Result Limit'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save question' }));
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(savedBody.parameters.map((p: ParameterDefinition) => p.name)).toEqual(['country', 'result_count']);
    expect(savedBody.parameters[0].allowed_values).toEqual(['USA', 'UK']);
    expect(savedBody.parameters[1].default_value).toBe(200);
  });

  it('edits definitions, explicitly replaces a revision, and asks for a variation', async () => {
    const patches: any[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit = {}) => {
      if (options.method === 'PATCH') {
        patches.push(JSON.parse(String(options.body)));
        return json({ ...sampleDetail, revision: 2 + patches.length });
      }
      return json(url.includes('?') ? { items: [sampleDetail], next_cursor: null } : sampleDetail);
    }));
    const variation = vi.fn();
    render(<SavedQuestionsManager connectionId="conn-1" onRunAccepted={vi.fn()} onAskVariation={variation} />);
    fireEvent.click(await screen.findByRole('button', { name: 'View or run' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Edit definition' }));
    fireEvent.change(screen.getByLabelText('Saved question title'), { target: { value: 'Updated' } });
    fireEvent.change(screen.getByLabelText('country display label'), { target: { value: 'Country' } });
    fireEvent.click(screen.getByLabelText('Expose order_date filter'));
    fireEvent.click(screen.getByRole('button', { name: 'Save definition' }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].expected_revision).toBe(2);
    expect(patches[0].parameters).toHaveLength(2);
    expect(patches[0].parameters[0].label).toBe('Country');
    fireEvent.click(await screen.findByRole('button', { name: 'Edit definition' }));
    fireEvent.change(screen.getByLabelText('Successful replacement run'), { target: { value: 'completed-42' } });
    fireEvent.click(screen.getByRole('button', { name: 'Replace stored SQL from run' }));
    await waitFor(() => expect(patches).toHaveLength(2));
    expect(patches[1]).toEqual({ expected_revision: 3, replacement_query_id: 'completed-42' });
    await screen.findByRole('button', { name: 'Ask for a variation' });
    fireEvent.change(screen.getByLabelText('Variation request'), { target: { value: 'Show only UK' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ask for a variation' }));
    expect(variation).toHaveBeenCalledWith(expect.stringContaining(sampleDetail.effective_question));
  });

  it('uses search and cursor pagination and ignores delayed connection responses', async () => {
    const urls: string[] = [];
    let resolveOld: (response: Response) => void = () => {};
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      urls.push(url);
      if (url.includes('connection_id=old')) return new Promise<Response>((resolve) => { resolveOld = resolve; });
      if (url.includes('cursor=')) return Promise.resolve(json({ items: [{ ...sampleDetail, id: 'next', title: 'Next page' }], next_cursor: null }));
      return Promise.resolve(json({ items: [sampleDetail], next_cursor: 'cursor-2' }));
    }));
    const { rerender } = render(<SavedQuestionsManager connectionId="old" onRunAccepted={vi.fn()} />);
    rerender(<SavedQuestionsManager connectionId="conn-1" onRunAccepted={vi.fn()} />);
    await screen.findByText(sampleDetail.title);
    resolveOld(json({ items: [{ ...sampleDetail, title: 'Stale connection' }], next_cursor: null }));
    fireEvent.change(screen.getByPlaceholderText('Search saved questions...'), { target: { value: 'monthly' } });
    await waitFor(() => expect(urls.some((url) => url.includes('search=monthly'))).toBe(true));
    fireEvent.click(await screen.findByRole('button', { name: 'Load more saved questions' }));
    await screen.findByText('Next page');
    expect(urls.some((url) => url.includes('cursor=cursor-2') && url.includes('search=monthly'))).toBe(true);
    expect(screen.queryByText('Stale connection')).not.toBeInTheDocument();
  });

  it('keeps integer category entry numeric and rejects fractional entries', () => {
    const onChange = vi.fn();
    render(<SavedQuestionFilters parameters={[{ ...sampleDefinitions[0], source_type: 'integer', default_value: 1, allowed_values: null }]}
      values={{ country: 1 }} onChange={onChange} />);
    const input = screen.getByLabelText('Customer Country');
    fireEvent.change(input, { target: { value: '2' } });
    expect(onChange).toHaveBeenCalledWith('country', 2);
    onChange.mockClear();
    fireEvent.change(input, { target: { value: '2.5' } });
    expect(onChange).not.toHaveBeenCalled();
  });
});

it('submits reviewed SQL as a new manual run without updating the saved definition', async () => {
  const writes: { url: string; body: any }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit = {}) => {
    if (options.method === 'POST' || options.method === 'PATCH') {
      writes.push({ url, body: JSON.parse(String(options.body)) });
      return new Response(JSON.stringify({ query_id: 'reviewed-run', status: 'queued' }), { status: 202 });
    }
    return new Response(JSON.stringify(url.includes('?') ? { items: [sampleDetail], next_cursor: null } : sampleDetail));
  }));
  const accepted = vi.fn();
  try {
    render(<SavedQuestionsManager connectionId="conn-1" onRunAccepted={accepted} />);
    fireEvent.click(await screen.findByRole('button', { name: 'View or run' }));
    const editor = await screen.findByLabelText('SQL for saved question review');
    fireEvent.change(editor, { target: { value: 'SELECT id FROM public.customers WHERE id > 2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run SQL for review' }));
    await waitFor(() => expect(accepted).toHaveBeenCalledWith('reviewed-run'));
    expect(writes).toEqual([{ url: '/api/v1/queries/sql', body: {
      connection_id: 'conn-1', sql: 'SELECT id FROM public.customers WHERE id > 2', max_rows: 100,
    } }]);
  } finally { vi.unstubAllGlobals(); }
});
