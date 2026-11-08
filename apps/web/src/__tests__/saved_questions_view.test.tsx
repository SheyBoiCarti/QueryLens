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

describe('Saved Questions Modal (Task 11)', () => {
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
