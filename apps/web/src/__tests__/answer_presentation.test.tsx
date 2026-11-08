import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { AnswerPresentation } from '../features/workspace/AnswerPresentation.tsx';
import { AccessibleChart } from '../features/workspace/charts/AccessibleChart.tsx';
import { plotValues } from '../features/workspace/charts/plotValues.ts';
import { PublicRunCompleted, ColumnMeta, PresentationMetadata } from '../api/generated/schema.ts';

const baseCompletedRun: PublicRunCompleted = {
  query_id: 'q-100',
  connection_id: 'c-1',
  status: 'completed',
  state_version: 1,
  question: 'Show monthly active users',
  created_at: '2026-11-08T12:00:00Z',
  updated_at: '2026-11-08T12:00:05Z',
  dialect: 'postgresql',
  sql: 'SELECT month, active_users FROM metrics ORDER BY month;',
  assumptions: ['Filtered to 2026 data'],
  warnings: ['Warning: partial month'],
  columns: [
    { name: 'month', type: 'date', db_type: 'date' },
    { name: 'active_users', type: 'integer', db_type: 'integer' },
  ],
  row_count: 3,
  truncated: false,
  results_available: true,
  results_expires_at: '2026-11-08T12:05:00Z',
  rows: [
    { month: '2026-01-01', active_users: 100 },
    { month: '2026-02-01', active_users: 150 },
    { month: '2026-03-01', active_users: 200 },
  ],
  presentation: {
    title: 'Monthly Active Users',
    explanation: '3 returned rows.',
    chart_type: 'line',
    x_column: 'month',
    y_column: 'active_users',
    plot_row_order: [0, 1, 2],
    units: 'users',
    warnings: ['Presentation warning: tentative'],
  },
};

describe('AnswerPresentation and AccessibleChart (Task 9)', () => {
  it('renders answer-first order: title, explanation, chart before collapsed SQL', () => {
    render(<AnswerPresentation run={baseCompletedRun} />);

    // Title and explanation at top
    expect(screen.getByRole('heading', { level: 3, name: 'Monthly Active Users' })).toBeInTheDocument();
    expect(screen.getByText('3 returned rows.')).toBeInTheDocument();

    // Warnings are visibly rendered
    expect(screen.getByText('Warning: partial month')).toBeInTheDocument();
    expect(screen.getByText('Presentation warning: tentative')).toBeInTheDocument();

    // SQL is in a collapsed details element
    const details = screen.getByRole('group', { name: /executed sql/i }) || screen.getByText(/executed sql/i).closest('details');
    expect(details).toBeInTheDocument();
    expect(details).not.toHaveAttribute('open');
  });

  it('preserves exact KPI strings beyond JavaScript safe integer range', () => {
    const hugeInteger = '9007199254740993'; // 2^53 + 1
    const kpiRun: PublicRunCompleted = {
      ...baseCompletedRun,
      columns: [{ name: 'total_count', type: 'integer', db_type: 'bigint' }],
      row_count: 1,
      rows: [{ total_count: hugeInteger }],
      presentation: {
        title: 'Total Metric Count',
        explanation: `total_count: ${hugeInteger}.`,
        chart_type: 'single_value',
        y_column: 'total_count',
        value: hugeInteger,
        units: 'events',
      },
    };

    render(<AnswerPresentation run={kpiRun} />);

    const kpiElement = screen.getByTestId('kpi-value');
    expect(kpiElement).toHaveTextContent(hugeInteger);
    expect(screen.getByText('events')).toBeInTheDocument();
  });

  it('allows switching between Chart and Table views with ARIA tabs', () => {
    render(<AnswerPresentation run={baseCompletedRun} />);

    const chartTab = screen.getByRole('tab', { name: /chart/i });
    const tableTab = screen.getByRole('tab', { name: /table/i });

    expect(chartTab).toHaveAttribute('aria-selected', 'true');
    expect(tableTab).toHaveAttribute('aria-selected', 'false');

    // Chart is visible
    expect(screen.getByRole('img', { name: /chart/i })).toBeInTheDocument();

    // Switch to table
    fireEvent.click(tableTab);
    expect(tableTab).toHaveAttribute('aria-selected', 'true');
    expect(chartTab).toHaveAttribute('aria-selected', 'false');

    // Table headers and cells are displayed
    expect(screen.getByText('active_users')).toBeInTheDocument();
    expect(screen.getByText('150')).toBeInTheDocument();
  });

  it('renders accessible SVG chart with exact points and labels', () => {
    render(<AccessibleChart presentation={baseCompletedRun.presentation} columns={baseCompletedRun.columns} rows={baseCompletedRun.rows!} />);

    const svg = screen.getByRole('img', { name: /chart/i });
    expect(svg).toBeInTheDocument();

    // Data points are present with accessible labels
    const points = screen.getAllByRole('graphics-symbol');
    expect(points.length).toBe(3);
    expect(points[0]).toHaveAttribute('aria-label', expect.stringContaining('100'));
    expect(points[1]).toHaveAttribute('aria-label', expect.stringContaining('150'));
    expect(points[2]).toHaveAttribute('aria-label', expect.stringContaining('200'));
  });

  it('clears volatile presentation and offers rerun when results expire', () => {
    const onRerun = vi.fn();
    const expiredRun: PublicRunCompleted = {
      ...baseCompletedRun,
      results_available: false,
      rows: undefined,
    };

    render(<AnswerPresentation run={expiredRun} onRerun={onRerun} />);

    // Volatile chart, rows, and result-derived KPI are cleared
    expect(screen.queryByRole('img', { name: /chart/i })).toBeNull();
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.queryByText('100')).toBeNull();

    // Notice is shown
    expect(screen.getByText(/results have expired or the connection policy changed/i)).toBeInTheDocument();

    // CSV link is absent or disabled
    expect(screen.queryByRole('link', { name: /download csv/i })).toBeNull();

    // Rerun button is offered
    const rerunBtn = screen.getByRole('button', { name: /rerun/i });
    fireEvent.click(rerunBtn);
    expect(onRerun).toHaveBeenCalledTimes(1);
  });
});

describe('plotValues eligibility rules (Task 9)', () => {
  it('falls back to table when row count exceeds 50 (e.g. 51 points)', () => {
    const rows = Array.from({ length: 51 }, (_, i) => ({
      day: `2026-01-${String(i + 1).padStart(2, '0')}`,
      count: i + 1,
    }));
    const pres: PresentationMetadata = {
      title: 'Too Many Points',
      explanation: '51 rows',
      chart_type: 'line',
      x_column: 'day',
      y_column: 'count',
    };
    const cols: ColumnMeta[] = [
      { name: 'day', type: 'date', db_type: 'date' },
      { name: 'count', type: 'integer', db_type: 'integer' },
    ];

    const result = plotValues(pres, cols, rows);
    expect(result.eligible).toBe(false);
  });

  it('falls back to table on null or empty keys', () => {
    const rows = [
      { day: '2026-01-01', count: 10 },
      { day: null, count: 20 },
    ];
    const pres: PresentationMetadata = {
      title: 'Null Key',
      explanation: '2 rows',
      chart_type: 'line',
      x_column: 'day',
      y_column: 'count',
    };
    const cols: ColumnMeta[] = [
      { name: 'day', type: 'date', db_type: 'date' },
      { name: 'count', type: 'integer', db_type: 'integer' },
    ];

    expect(plotValues(pres, cols, rows).eligible).toBe(false);
  });

  it('falls back to table on duplicate keys', () => {
    const rows = [
      { day: '2026-01-01', count: 10 },
      { day: '2026-01-01', count: 20 },
    ];
    const pres: PresentationMetadata = {
      title: 'Duplicate Keys',
      explanation: '2 rows',
      chart_type: 'line',
      x_column: 'day',
      y_column: 'count',
    };
    const cols: ColumnMeta[] = [
      { name: 'day', type: 'date', db_type: 'date' },
      { name: 'count', type: 'integer', db_type: 'integer' },
    ];

    expect(plotValues(pres, cols, rows).eligible).toBe(false);
  });

  it('falls back to table when numeric-looking column is declared as string', () => {
    const rows = [
      { category: 'A', amount_str: '100' },
      { category: 'B', amount_str: '200' },
    ];
    const pres: PresentationMetadata = {
      title: 'String Amount',
      explanation: '2 rows',
      chart_type: 'bar',
      x_column: 'category',
      y_column: 'amount_str',
    };
    const cols: ColumnMeta[] = [
      { name: 'category', type: 'string', db_type: 'varchar' },
      { name: 'amount_str', type: 'string', db_type: 'varchar' }, // declared as string!
    ];

    expect(plotValues(pres, cols, rows).eligible).toBe(false);
  });

  it('falls back to table on unsafe numbers beyond JS safe integer range', () => {
    const rows = [
      { category: 'A', value: '9007199254740993' }, // unsafe int
      { category: 'B', value: '100' },
    ];
    const pres: PresentationMetadata = {
      title: 'Unsafe Number',
      explanation: '2 rows',
      chart_type: 'bar',
      x_column: 'category',
      y_column: 'value',
    };
    const cols: ColumnMeta[] = [
      { name: 'category', type: 'string', db_type: 'varchar' },
      { name: 'value', type: 'integer', db_type: 'bigint' },
    ];

    expect(plotValues(pres, cols, rows).eligible).toBe(false);
  });
});

describe('WorkspaceView Expiry and Revalidation (Task 9)', () => {
  const connectionItem = { id: 'c-1', name: 'Main DB', engine: 'postgresql', host: 'localhost', port: 5432, database: 'db', username: 'u' };

  it('handles expiry timer and clears volatile rows at results_expires_at', async () => {
    vi.useFakeTimers();
    const startTime = 1700000000000;
    vi.setSystemTime(startTime);

    const expiresAt = new Date(startTime + 5000).toISOString();
    let currentRun = {
      ...baseCompletedRun,
      results_available: true,
      results_expires_at: expiresAt,
    };

    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/q-100/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/q-100')) {
        return new Response(JSON.stringify(currentRun), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { WorkspaceView } = await import('../features/workspace/WorkspaceView.tsx');
    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="q-100" />);

    // Allow initial poll to resolve
    await vi.advanceTimersByTimeAsync(100);

    // Initial state: Chart or table is visible
    expect(screen.getByRole('heading', { level: 3, name: 'Monthly Active Users' })).toBeInTheDocument();
    expect(screen.queryByText(/results have expired/i)).toBeNull();

    // Advance past expiry
    currentRun = {
      ...currentRun,
      results_available: false,
      rows: undefined,
    };
    await vi.advanceTimersByTimeAsync(5500);

    // After expiry: volatile rows are cleared and notice is visible
    expect(screen.getByText(/results have expired/i)).toBeInTheDocument();

    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('discovers early eviction with unchanged state_version on periodic revalidation', async () => {
    vi.useFakeTimers();
    const startTime = new Date('2026-11-08T12:00:00Z').getTime();
    vi.setSystemTime(startTime);
    let currentRun: any = {
      ...baseCompletedRun,
      results_expires_at: new Date(startTime + 600000).toISOString(),
      state_version: 2,
      results_available: true,
    };

    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/q-100/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/q-100')) {
        return new Response(JSON.stringify(currentRun), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { WorkspaceView } = await import('../features/workspace/WorkspaceView.tsx');
    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="q-100" />);

    await vi.advanceTimersByTimeAsync(100);
    expect(screen.queryByText(/results have expired/i)).toBeNull();

    // Cache evicted early: state_version stays 2, but results_available becomes false
    currentRun = {
      ...currentRun,
      state_version: 2, // unchanged!
      results_available: false,
      rows: undefined,
    };

    // Advance by 30s revalidation interval
    await vi.advanceTimersByTimeAsync(31000);

    // Availability change must NOT be discarded by state_version comparison
    expect(screen.getByText(/results have expired/i)).toBeInTheDocument();

    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('clears protected data on authorization revocation (HTTP 403)', async () => {
    vi.useFakeTimers();
    const startTime = new Date('2026-11-08T12:00:00Z').getTime();
    vi.setSystemTime(startTime);
    let pollCount = 0;

    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/connections')) {
        return new Response(JSON.stringify([connectionItem]), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/q-100/trace')) {
        return new Response(JSON.stringify({ status: 'completed' }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes('/api/v1/queries/q-100')) {
        pollCount += 1;
        if (pollCount > 1) {
          // Revocation
          return new Response(JSON.stringify({ detail: 'Access denied' }), { status: 403, headers: { 'Content-Type': 'application/json' } });
        }
        return new Response(JSON.stringify(baseCompletedRun), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { WorkspaceView } = await import('../features/workspace/WorkspaceView.tsx');
    render(<WorkspaceView onNavigateToConnections={vi.fn()} initialQueryId="q-100" />);

    await vi.advanceTimersByTimeAsync(100);
    expect(screen.getByRole('heading', { level: 3, name: 'Monthly Active Users' })).toBeInTheDocument();

    // Trigger revalidation after 30s
    await vi.advanceTimersByTimeAsync(31000);

    // Protected title and chart are cleared
    expect(screen.queryByRole('heading', { level: 3, name: 'Monthly Active Users' })).toBeNull();
    expect(screen.queryByRole('img', { name: /chart/i })).toBeNull();

    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
