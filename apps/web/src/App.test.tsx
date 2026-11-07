import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from './App.tsx';

describe('App Shell Smoke Test', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('renders application title and loading indicator initially', () => {
    vi.spyOn(global, 'fetch').mockImplementation(() => new Promise(() => {}));
    render(<App />);
    expect(screen.getByText('QueryLens')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/Checking API/i);
  });

  it('renders connected status when health probe succeeds', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'ok', metadata_db: 'healthy' }),
    } as Response);

    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/API Connected \(healthy\)/i);
    });
  });

  it('renders offline status when network call fails without unhandled rejection', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValueOnce(new Error('Network error'));

    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/API Offline/i);
    });
  });
});
