import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { SQLPanel } from '../features/workspace/SQLPanel.tsx';

describe('Editable SQLPanel (Task 10)', () => {
  it('renders read-only executed SQL initially and toggles to edit mode', () => {
    const executedSql = 'SELECT id, name FROM users;';
    render(<SQLPanel sql={executedSql} dialect="postgresql" runId="run-1" />);

    expect(screen.getByText(executedSql)).toBeInTheDocument();

    const editBtn = screen.getByRole('button', { name: /edit sql/i });
    fireEvent.click(editBtn);

    const textarea = screen.getByRole('textbox', { name: /sql editor/i });
    expect(textarea).toHaveValue(executedSql);
  });

  it('calls onRunSql with modified draft when Run edited SQL is clicked', async () => {
    const executedSql = 'SELECT id, name FROM users;';
    const onRunSql = vi.fn().mockResolvedValue(undefined);

    render(
      <SQLPanel
        sql={executedSql}
        dialect="postgresql"
        runId="run-1"
        onRunSql={onRunSql}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /edit sql/i }));

    const textarea = screen.getByRole('textbox', { name: /sql editor/i });
    fireEvent.change(textarea, { target: { value: 'SELECT id, name, email FROM users;' } });

    const runBtn = screen.getByRole('button', { name: /run edited sql/i });
    fireEvent.click(runBtn);

    expect(onRunSql).toHaveBeenCalledWith('SELECT id, name, email FROM users;');
  });

  it('prompts confirmation when canceling a dirty draft and keeps draft on cancel reject', () => {
    const executedSql = 'SELECT id FROM users;';
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    render(<SQLPanel sql={executedSql} dialect="postgresql" runId="run-1" />);

    fireEvent.click(screen.getByRole('button', { name: /edit sql/i }));

    const textarea = screen.getByRole('textbox', { name: /sql editor/i });
    fireEvent.change(textarea, { target: { value: 'SELECT id, role FROM users;' } });

    // Cancel edit
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    fireEvent.click(cancelBtn);

    expect(confirmSpy).toHaveBeenCalled();
    // Since confirm returned false, textarea remains open with dirty draft
    expect(screen.getByRole('textbox', { name: /sql editor/i })).toHaveValue('SELECT id, role FROM users;');

    confirmSpy.mockRestore();
  });

  it('disables textarea and run button when disabled prop is true', () => {
    render(
      <SQLPanel
        sql="SELECT 1;"
        dialect="postgresql"
        runId="run-1"
        disabled={true}
        onRunSql={vi.fn()}
      />
    );

    const editBtn = screen.getByRole('button', { name: /edit sql/i });
    expect(editBtn).toBeDisabled();
  });
});
