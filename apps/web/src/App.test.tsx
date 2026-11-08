import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from './App.tsx';
import { api, ApiError } from './api/client.ts';

// Authentication is the actual application gate. No tests were run during remediation.
describe('Application session restoration', () => {
  beforeEach(() => { vi.restoreAllMocks(); window.location.hash = ''; });

  it('shows session restoration while authentication is pending', () => {
    vi.spyOn(api, 'getMe').mockImplementation(() => new Promise(() => {}));
    render(<App />);
    expect(screen.getByText('QueryLens')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/Restoring your session/i);
  });

  it('shows a reachable login when the session has expired', async () => {
    vi.spyOn(api, 'getMe').mockRejectedValue(new ApiError('UNAUTHORIZED', 'Sign in', '', 401));
    render(<App />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Sign in to QueryLens' })).toBeInTheDocument());
  });

  it('shows a recoverable connection error without pretending the user is logged out successfully', async () => {
    vi.spyOn(api, 'getMe').mockRejectedValue(new Error('Network error'));
    render(<App />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Network error'));
    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeInTheDocument();
  });
});
