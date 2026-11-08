import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setCsrfToken } from '../api/client.ts';
import { CatalogSnapshot } from '../api/catalog.ts';
import { MetricResponse } from '../api/generated/schema.ts';
import { LabelManager } from '../features/schema/LabelManager.tsx';
import { MetricEditor } from '../features/schema/MetricEditor.tsx';
import { Metrics } from '../features/schema/Metrics.tsx';
import { SchemaExplorer } from '../features/schema/SchemaExplorer.tsx';

const catalog: CatalogSnapshot = {
  connection_id: 'one', engine: 'postgres', snapshot_hash: 'hash', policy_version: 1,
  tables: [{ namespace: 'public', name: 'orders', primary_key_columns: [], foreign_keys: [], columns: [
    { name: 'amount', canonical_type: 'decimal', db_type: 'numeric', nullable: false, primary_key: false },
    { name: 'region', canonical_type: 'string', db_type: 'text', nullable: false, primary_key: false },
    { name: 'active', canonical_type: 'boolean', db_type: 'bool', nullable: false, primary_key: false },
  ] }],
};
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const fetchMock = vi.fn();
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const metric: MetricResponse = { id: 'metric', connection_id: 'one', key: 'revenue', name: 'Revenue', description: 'Original', version: 3, enabled: true,
  dsl: { key: 'revenue', name: 'Revenue', description: 'Original', table: 'public.orders', measure_column: 'amount', aggregation: 'sum', units: 'USD', synonyms: ['Sales'], filters: [], grain: ['region'] } };

beforeEach(() => { vi.stubGlobal('fetch', fetchMock); fetchMock.mockReset(); setCsrfToken('csrf'); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); setCsrfToken(null); });

describe('business labels at the HTTP boundary', () => {
  it('loads, replaces table/column metadata with version and CSRF, and reloads persisted values', async () => {
    let persisted = { semantic_version: 4, labels: [{ namespace: 'public', table_name: 'orders', column_name: null, display_name: 'Orders', description: null, version: 1 }] };
    fetchMock.mockImplementation(async (_url: string, options: RequestInit) => {
      if (options.method === 'PUT') {
        const body = JSON.parse(options.body as string);
        persisted = { semantic_version: 5, labels: body.labels.map((label: object) => ({ ...label, version: 2 })) };
      }
      return response(persisted);
    });
    const view = render(<LabelManager connectionId="one" tables={catalog.tables} onSaved={vi.fn()} />);
    await screen.findByDisplayValue('Orders');
    change('public.orders display name', 'Purchases');
    change('public.orders description', 'Paid orders');
    change('public.orders.amount display name', 'Revenue');
    change('public.orders.amount description', 'Before tax');
    fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toBe('/api/v1/connections/one/labels');
    expect(options.method).toBe('PUT');
    expect(options.credentials).toBe('include');
    expect(options.headers.get('X-CSRF-Token')).toBe('csrf');
    expect(options.headers.get('X-QueryLens-Client')).toBe('web');
    expect(JSON.parse(options.body)).toEqual({ expected_semantic_version: 4, labels: [
      { namespace: 'public', table_name: 'orders', column_name: null, display_name: 'Purchases', description: 'Paid orders' },
      { namespace: 'public', table_name: 'orders', column_name: 'amount', display_name: 'Revenue', description: 'Before tax' },
    ] });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save labels' })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(JSON.parse(fetchMock.mock.calls[2][1].body).expected_semantic_version).toBe(5);
    view.unmount();
    render(<LabelManager connectionId="one" tables={catalog.tables} onSaved={vi.fn()} />);
    await screen.findByDisplayValue('Purchases');
    expect(screen.getByLabelText('public.orders.amount description')).toHaveValue('Before tax');
  });

  it.each([409, 422])('retains the draft and expected version on HTTP %s', async (status) => {
    fetchMock.mockResolvedValueOnce(response({ semantic_version: 8, labels: [] }))
      .mockResolvedValueOnce(response({ error: { code: 'CONFLICT', message: 'Please review labels' } }, status));
    render(<LabelManager connectionId="one" tables={catalog.tables} onSaved={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save labels' })).not.toBeDisabled());
    change('public.orders display name', 'Draft');
    fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Please review labels');
    expect(screen.getByLabelText('public.orders display name')).toHaveValue('Draft');
  });

  it('ignores a late label response from the previous connection', async () => {
    let finishOld!: (value: Response) => void;
    fetchMock.mockImplementation((url: string) => url.includes('/one/')
      ? new Promise<Response>((resolve) => { finishOld = resolve; })
      : Promise.resolve(response({ semantic_version: 2, labels: [{ namespace: 'public', table_name: 'orders', column_name: null, display_name: 'New connection', version: 1 }] })));
    const view = render(<LabelManager connectionId="one" tables={catalog.tables} onSaved={vi.fn()} />);
    view.rerender(<LabelManager connectionId="two" tables={catalog.tables} onSaved={vi.fn()} />);
    await screen.findByDisplayValue('New connection');
    await act(async () => finishOld(response({ semantic_version: 9, labels: [{ namespace: 'public', table_name: 'orders', column_name: null, display_name: 'Stale', version: 1 }] })));
    expect(screen.getByLabelText('public.orders display name')).toHaveValue('New connection');
  });
});

describe('complete structured metric editor', () => {
  it('creates the full DSL using authorized physical selectors and typed filters', async () => {
    const onSaved = vi.fn();
    fetchMock.mockResolvedValue(response(metric));
    render(<MetricEditor connectionId="one" catalog={catalog} onSaved={onSaved} onCancel={vi.fn()} />);
    change('Metric key', 'revenue'); change('Display name', 'Revenue'); change('Description', 'Paid revenue');
    change('Units', 'USD'); change('Synonyms (one per line)', 'Sales\nTurnover');
    change('Table', 'public.orders'); change('Measure column', 'amount'); change('Aggregation', 'count_distinct');
    fireEvent.click(screen.getByLabelText('Grain region'));
    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    change('Filter 1 column', 'amount'); change('Filter 1 operator', 'gte'); change('Filter 1 value type', 'number'); change('Filter 1 value', '12.5');
    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    change('Filter 2 column', 'region'); change('Filter 2 operator', 'in'); change('Filter 2 value', '["ZA","US"]');
    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    change('Filter 3 column', 'active'); change('Filter 3 value type', 'boolean'); change('Filter 3 value', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Save metric' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/connections/one/metrics');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ key: 'revenue', name: 'Revenue', description: 'Paid revenue', units: 'USD', synonyms: ['Sales', 'Turnover'], table: 'public.orders', measure_column: 'amount', aggregation: 'count_distinct', grain: ['region'], filters: [
      { column: 'amount', operator: 'gte', value: 12.5 }, { column: 'region', operator: 'in', value: ['ZA', 'US'] }, { column: 'active', operator: 'eq', value: true },
    ] });
  });

  it.each([409, 422])('patches all existing fields with optimistic version and retains drafts on HTTP %s', async (status) => {
    fetchMock.mockResolvedValueOnce(response({ error: { code: 'CONFLICT', message: 'Metric changed' } }, status))
      .mockResolvedValueOnce(response({ ...metric, version: 4 }));
    const onSaved = vi.fn();
    render(<MetricEditor connectionId="one" catalog={catalog} metric={metric} onSaved={onSaved} onCancel={vi.fn()} />);
    expect(screen.getByLabelText('Synonyms (one per line)')).toHaveValue('Sales');
    change('Synonyms (one per line)', 'Turnover');
    fireEvent.click(screen.getByRole('button', { name: 'Save metric' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Metric changed');
    expect(screen.getByLabelText('Synonyms (one per line)')).toHaveValue('Turnover');
    expect(onSaved).not.toHaveBeenCalled();
    const options = fetchMock.mock.calls[0][1];
    expect(options.method).toBe('PATCH');
    expect(JSON.parse(options.body)).toEqual({ expected_version: 3, enabled: true, dsl: { ...metric.dsl, synonyms: ['Turnover'] } });
  });

  it('offers all operators, handles null predicates, and rejects invalid typed values before HTTP', async () => {
    render(<MetricEditor connectionId="one" catalog={catalog} metric={{ ...metric, dsl: { ...metric.dsl, filters: [{ column: 'region', operator: 'not_in', value: ['ZA'] }, { column: 'amount', operator: 'is_null', value: null }] } }} onSaved={vi.fn()} onCancel={vi.fn()} />);
    const operators = screen.getByLabelText('Filter 1 operator') as HTMLSelectElement;
    expect(Array.from(operators.options, (option) => option.value)).toEqual(['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in', 'is_null', 'is_not_null']);
    expect(screen.getByLabelText('Filter 1 value')).toHaveValue('["ZA"]');
    expect(screen.queryByLabelText('Filter 2 value')).toBeNull();
    change('Filter 1 value', '[{}]');
    fireEvent.click(screen.getByRole('button', { name: 'Save metric' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/scalar/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('connection request isolation', () => {
  it('ignores a completed label save after the connection changes', async () => {
    let finishSave!: (value: Response) => void;
    fetchMock.mockImplementation((_url: string, options: RequestInit) => options.method === 'PUT'
      ? new Promise<Response>((resolve) => { finishSave = resolve; })
      : Promise.resolve(response({ semantic_version: 2, labels: [] })));
    const onSaved = vi.fn();
    const view = render(<LabelManager connectionId="one" tables={catalog.tables} onSaved={onSaved} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save labels' })).not.toBeDisabled());
    change('public.orders display name', 'Old draft');
    fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
    view.rerender(<LabelManager connectionId="two" tables={catalog.tables} onSaved={onSaved} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save labels' })).not.toBeDisabled());
    await act(async () => finishSave(response({ semantic_version: 3, labels: [{ namespace: 'public', table_name: 'orders', display_name: 'Old saved name', version: 2 }] })));
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText('public.orders display name')).toHaveValue('');
  });

  it('ignores a completed metric save after the connection changes', async () => {
    let finishSave!: (value: Response) => void;
    fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { finishSave = resolve; }));
    const onSaved = vi.fn();
    const view = render(<MetricEditor connectionId="one" catalog={catalog} metric={metric} onSaved={onSaved} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Save metric' }));
    view.rerender(<MetricEditor connectionId="two" catalog={{ ...catalog, connection_id: 'two' }} onSaved={onSaved} onCancel={vi.fn()} />);
    await act(async () => finishSave(response({ ...metric, version: 4 })));
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Display name')).toHaveValue('');
  });

  it('excludes invisible labels from replacement requests', async () => {
    fetchMock.mockResolvedValueOnce(response({ semantic_version: 3, labels: [{ namespace: 'hidden', table_name: 'payroll', display_name: 'Salaries', version: 1 }] }))
      .mockResolvedValueOnce(response({ semantic_version: 4, labels: [] }));
    render(<LabelManager connectionId="one" tables={catalog.tables} onSaved={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save labels' })).not.toBeDisabled());
    expect(screen.queryByText('hidden.payroll')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Save labels' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).labels).toEqual([]);
  });
});

describe('schema and metric integration', () => {
  it('loads persisted metric versions and reopens updated DSL after a save', async () => {
    let persisted = metric;
    fetchMock.mockImplementation(async (_url: string, options: RequestInit) => {
      if (options.method === 'PATCH') {
        const body = JSON.parse(options.body as string);
        persisted = { ...metric, ...body.dsl, dsl: body.dsl, version: 4 };
        return response(persisted);
      }
      return response([persisted]);
    });
    render(<Metrics connectionId="one" catalog={catalog} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit Revenue' }));
    change('Synonyms (one per line)', 'Turnover');
    fireEvent.click(screen.getByRole('button', { name: 'Save metric' }));
    await screen.findByText('Also called: Turnover');
    fireEvent.click(screen.getByRole('button', { name: 'Edit Revenue' }));
    expect(screen.getByLabelText('Synonyms (one per line)')).toHaveValue('Turnover');
    fireEvent.click(screen.getByRole('button', { name: 'Save metric' }));
    await waitFor(() => expect(fetchMock.mock.calls.filter((call) => call[1].method === 'PATCH')).toHaveLength(2));
    expect(JSON.parse(fetchMock.mock.calls.filter((call) => call[1].method === 'PATCH')[1][1].body).expected_version).toBe(4);
  });

  it('ignores stale metric list responses', async () => {
    let finishOld!: (value: Response) => void;
    fetchMock.mockImplementation((url: string) => url.includes('/one/')
      ? new Promise<Response>((resolve) => { finishOld = resolve; }) : Promise.resolve(response([])));
    const view = render(<Metrics connectionId="one" catalog={catalog} />);
    view.rerender(<Metrics connectionId="two" catalog={{ ...catalog, connection_id: 'two' }} />);
    await act(async () => finishOld(response([metric])));
    expect(screen.queryByRole('button', { name: 'Edit Revenue' })).toBeNull();
  });

  it('keeps physical names inspectable alongside business labels and ignores stale catalogs', async () => {
    let finishOld!: (value: Response) => void;
    const labels = { semantic_version: 2, labels: [
      { namespace: 'public', table_name: 'orders', column_name: null, display_name: 'Purchases', description: 'Paid orders', version: 1 },
      { namespace: 'public', table_name: 'orders', column_name: 'amount', display_name: 'Revenue', description: 'Before tax', version: 1 },
    ] };
    fetchMock.mockImplementation((url: string) => {
      if (url === '/api/v1/connections') return Promise.resolve(response([{ id: 'one', name: 'First' }, { id: 'two', name: 'Second' }]));
      if (url.endsWith('/metrics')) return Promise.resolve(response([]));
      if (url.endsWith('/labels')) return Promise.resolve(response(labels));
      if (url === '/api/v1/connections/one/schema') return new Promise<Response>((resolve) => { finishOld = resolve; });
      return Promise.resolve(response({ ...catalog, connection_id: 'two' }));
    });
    const view = render(<SchemaExplorer connectionId="one" />);
    view.rerender(<SchemaExplorer connectionId="two" />);
    await screen.findByRole('button', { name: 'Purchases public.orders' });
    expect(screen.getByRole('heading', { name: 'orders' })).toBeInTheDocument();
    expect(screen.getByText('Before tax')).toBeInTheDocument();
    expect(screen.getByText('amount', { selector: 'span' })).toBeInTheDocument();
    await act(async () => finishOld(response({ ...catalog, tables: [{ ...catalog.tables[0], name: 'stale_table' }] })));
    expect(screen.queryByRole('heading', { name: 'stale_table' })).toBeNull();
    expect(screen.getByRole('heading', { name: 'orders' })).toBeInTheDocument();
  });
});
