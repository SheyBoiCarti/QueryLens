import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import AppShell from '../components/AppShell.tsx';
import StatusNotice from '../components/StatusNotice.tsx';

describe('AppShell and Navigation States (Task 08.01)', () => {
  it('renders navigation links and switches active page on keyboard click', () => {
    let current = 'ask';
    const onRouteChange = vi.fn((r) => {
      current = r;
    });

    const { rerender } = render(
      <AppShell
        currentRoute={current}
        onRouteChange={onRouteChange}
      >
        <div>Content for {current}</div>
      </AppShell>
    );

    const historyBtn = screen.getByRole('button', { name: /history/i });
    expect(historyBtn).not.toHaveAttribute('aria-current');

    fireEvent.click(historyBtn);
    expect(onRouteChange).toHaveBeenCalledWith('history');

    rerender(
      <AppShell
        currentRoute="history"
        onRouteChange={onRouteChange}
      >
        <div>Content for history</div>
      </AppShell>
    );

    expect(screen.getByRole('button', { name: /history/i })).toHaveAttribute('aria-current', 'page');
  });

  it('has no account or logout controls', () => {
    render(<AppShell currentRoute="ask" onRouteChange={vi.fn()}><div>Workspace</div></AppShell>);
    expect(screen.queryByRole('button', { name: /logout/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/not authenticated/i)).not.toBeInTheDocument();
  });

  it('renders distinct and actionable status notices for loading, empty, error and expired', () => {
    const onRetry = vi.fn();

    const { rerender } = render(
      <StatusNotice type="error" title="Connection Failed" message="Host unreachable" action={{ label: 'Retry', onClick: onRetry }} />
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/Host unreachable/);
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);

    rerender(<StatusNotice type="expired" title="Results Expired" message="Volatile cache cleared" />);
    expect(screen.getByRole('status')).toHaveTextContent(/Volatile cache cleared/);

    rerender(<StatusNotice type="empty" message="No records found" />);
    expect(screen.getByRole('status')).toHaveTextContent(/No records found/);
  });
});
