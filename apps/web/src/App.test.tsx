import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import App from './App.tsx';

vi.mock('./features/workspace/WorkspaceView.tsx', () => ({ WorkspaceView: () => <div>Query workspace</div> }));

describe('Application without authentication', () => {
  it('opens the workspace immediately without a session', () => {
    window.location.hash = '';
    render(<App />);
    expect(screen.getByText('Query workspace')).toBeInTheDocument();
    expect(screen.queryByText(/sign in|restoring your session/i)).not.toBeInTheDocument();
  });
});
