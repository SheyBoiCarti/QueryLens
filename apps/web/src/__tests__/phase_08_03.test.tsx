import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { compareCell, compareDecimalStrings } from '../components/resultComparators.ts';
import DataGrid, { ColumnMeta } from '../components/DataGrid.tsx';

describe('Result Comparators & DataGrid (Task 08.03)', () => {
  it('sorts big integers beyond Number.MAX_SAFE_INTEGER without precision loss', () => {
    const a = '9007199254740992';
    const b = '9007199254740993';

    // In JS float: Number(a) === Number(b) is true!
    expect(Number(a) === Number(b)).toBe(true);

    // Exact string comparator must distinguish them correctly
    expect(compareDecimalStrings(a, b)).toBe(-1);
    expect(compareDecimalStrings(b, a)).toBe(1);
    expect(compareCell(a, b, 'integer')).toBe(-1);
  });

  it('sorts close high-precision decimals correctly', () => {
    const d1 = '100.0000000000000001';
    const d2 = '100.0000000000000002';
    expect(compareDecimalStrings(d1, d2)).toBe(-1);
    expect(compareDecimalStrings(d2, d1)).toBe(1);
  });

  it('preserves text semantics for numeric-looking strings like 001 versus 1', () => {
    const t1 = '001';
    const t2 = '1';
    expect(compareCell(t1, t2, 'string')).toBe(-1);
    expect(compareCell(t2, t1, 'string')).toBe(1);
  });

  it('handles null values stably in both directions', () => {
    expect(compareCell(null, null, 'decimal')).toBe(0);
    expect(compareCell('10', null, 'decimal')).toBe(-1);
    expect(compareCell(null, '10', 'decimal')).toBe(1);
  });

  it('updates aria-sort and handles duplicate column names uniquely in DataGrid', () => {
    const columns: ColumnMeta[] = [
      { name: 'amount', type: 'decimal' },
      { name: 'amount', type: 'decimal' }, // Duplicate column name
    ];
    const rows = [
      { amount: '50.00' },
      { amount: '10.00' },
      { amount: '100.00' },
    ];

    render(<DataGrid columns={columns} rows={rows} />);

    const sortButtons = screen.getAllByRole('button', { name: /sort by amount/i });
    expect(sortButtons.length).toBe(2);

    const firstHeader = sortButtons[0].closest('th');
    expect(firstHeader).toHaveAttribute('aria-sort', 'none');

    // Click to sort ascending
    fireEvent.click(sortButtons[0]);
    expect(firstHeader).toHaveAttribute('aria-sort', 'ascending');

    // Click to sort descending
    fireEvent.click(sortButtons[0]);
    expect(firstHeader).toHaveAttribute('aria-sort', 'descending');
  });

  it('displays distinct truncation alert and zero-row messages', () => {
    const { rerender } = render(
      <DataGrid columns={[{ name: 'id', type: 'integer' }]} rows={[]} />
    );
    expect(screen.getByText('Query returned zero rows.')).toBeInTheDocument();

    rerender(
      <DataGrid
        columns={[{ name: 'id', type: 'integer' }]}
        rows={[{ id: '1' }]}
        truncated={true}
      />
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/Result set was truncated at server limit/);
  });
});
