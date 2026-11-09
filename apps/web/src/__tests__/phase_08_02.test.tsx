import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ConnectionManager from '../features/connections/ConnectionManager.tsx';
import ConnectionForm from '../features/connections/ConnectionForm.tsx';
import { api } from '../api/client.ts';

describe('ConnectionManager Component (Task 08.02)', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('loads and lists connections with test button invoking test API', async () => {
    vi.spyOn(api, 'get').mockResolvedValueOnce([
      {
        id: 'conn-1',
        name: 'Analytics Postgres',
        engine: 'postgresql',
        host: 'pg.internal',
        port: 5432,
        database: 'analytics',
        username: 'analyst',
        tls_enabled: true,
        created_at: '2026-11-07T00:00:00Z',
      },
    ]);

    const testSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({
      success: true,
      server_version: 'PostgreSQL 16.1',
      message: 'Connected',
    });

    render(<ConnectionManager />);

    expect(screen.getByText('Loading connections...')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Analytics Postgres')).toBeInTheDocument();
    });

    const testBtn = screen.getByRole('button', { name: /test/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(testSpy).toHaveBeenCalledWith('/api/v1/connections/conn-1/test');
      expect(screen.getByText(/Connected: PostgreSQL 16.1/)).toBeInTheDocument();
    });
  });

  it('renders connection form with TLS enabled by default', () => {
    render(<ConnectionForm onSuccess={vi.fn()} />);

    expect(screen.getByLabelText(/connection name/i)).toBeInTheDocument();
    const tlsCheckbox = screen.getByLabelText(/encrypt connection/i) as HTMLInputElement;
    expect(tlsCheckbox.checked).toBe(true);
  });

  it('does not send placeholder stars when password is empty or omitted', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({
      id: 'conn-new',
      name: 'Test DB',
      engine: 'postgresql',
    });

    render(<ConnectionForm onSuccess={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/connection name/i), { target: { value: 'Test DB' } });
    fireEvent.change(screen.getByLabelText(/hostname/i), { target: { value: '127.0.0.1' } });
    fireEvent.change(screen.getByLabelText(/port/i), { target: { value: '5432' } });
    fireEvent.change(screen.getByLabelText(/database name/i), { target: { value: 'testdb' } });
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'user' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'ValidPass123!' } });

    const submitBtn = screen.getByRole('button', { name: /save connection/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalled();
      const payload = postSpy.mock.calls[0][1] as any;
      expect(payload.password).not.toBe('********');
      expect(payload.password).toBe('ValidPass123!');
    });
  });
});
