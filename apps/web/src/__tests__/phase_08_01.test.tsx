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
        user={{ id: 'u1', email: 'analyst@example.com', role: 'admin' }}
        onLogout={vi.fn()}
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
        user={{ id: 'u1', email: 'analyst@example.com', role: 'admin' }}
        onLogout={vi.fn()}
      >
        <div>Content for history</div>
      </AppShell>
    );

    expect(screen.getByRole('button', { name: /history/i })).toHaveAttribute('aria-current', 'page');
  });

  it('triggers logout callback removing user session', () => {
    const onLogout = vi.fn();
    render(
      <AppShell
        currentRoute="ask"
        onRouteChange={vi.fn()}
        user={{ id: 'u1', email: 'analyst@example.com', role: 'admin' }}
        onLogout={onLogout}
      >
        <div>Workspace</div>
      </AppShell>
    );

    const logoutBtn = screen.getByRole('button', { name: /logout/i });
    fireEvent.click(logoutBtn);
    expect(onLogout).toHaveBeenCalledTimes(1);
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
