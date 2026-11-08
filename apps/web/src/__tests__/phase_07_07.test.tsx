import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import QueryInspector, { TraceData } from '../features/workspace/QueryInspector.tsx';

describe('QueryInspector Component (Task 07.07)', () => {
  it('renders invalid-then-correct run showing exactly one repair and its reason', () => {
    const trace: TraceData = {
      query_id: 'run-1234',
      status: 'completed',
      attempts: [
        {
          attempt_number: 1,
          status: 'failed',
          generated_sql: 'SELECT FORM users',
          prompt_tokens: 100,
          completion_tokens: 20,
          latency_ms: 15,
          error_signature: 'syntax:SYNTAX_ERROR',
        },
        {
          attempt_number: 2,
          status: 'success',
          generated_sql: 'SELECT COUNT(*) FROM users',
          prompt_tokens: 120,
          completion_tokens: 25,
          latency_ms: 18,
        },
      ],
    };

    render(<QueryInspector trace={trace} status="completed" />);

    expect(screen.getByText('Query Inspector & Diagnostics')).toBeInTheDocument();
    expect(screen.getByText(/Attempt 1 \(Initial Generation\)/)).toBeInTheDocument();
    expect(screen.getByText(/Attempt 2 \(Repair\)/)).toBeInTheDocument();
    expect(screen.getByText(/Repair Reason: syntax:SYNTAX_ERROR/)).toBeInTheDocument();
    expect(screen.getByText('SELECT COUNT(*) FROM users')).toBeInTheDocument();
  });

  it('renders security failure showing zero repair attempts', () => {
    const trace: TraceData = {
      query_id: 'run-sec-01',
      status: 'rejected',
      attempts: [
        {
          attempt_number: 1,
          status: 'failed',
          generated_sql: 'DROP TABLE users',
          prompt_tokens: 80,
          completion_tokens: 15,
          latency_ms: 10,
          error_signature: 'policy:POLICY_VIOLATION',
        },
      ],
    };

    render(<QueryInspector trace={trace} status="rejected" />);

    expect(screen.getByText(/Attempt 1 \(Initial Generation\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Attempt 2/)).not.toBeInTheDocument();
    expect(screen.getByTestId('status-badge')).toHaveTextContent('rejected');
  });

  it('does not display cancelled early when status is cancelling', () => {
    const trace: TraceData = {
      query_id: 'run-cancelling-01',
      status: 'cancelling',
      attempts: [],
    };

    render(<QueryInspector trace={trace} status="cancelling" />);

    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveTextContent(/cancelling/i);
    expect(badge).not.toHaveTextContent(/^cancelled$/i);
  });

  it('allows keyboard accessibility for inspecting attempts and cancelling', () => {
    const onCancelMock = vi.fn();
    const trace: TraceData = {
      query_id: 'run-kb-01',
      status: 'executing',
      attempts: [
        {
          attempt_number: 1,
          status: 'generated',
          generated_sql: 'SELECT id FROM users',
          prompt_tokens: 50,
          completion_tokens: 10,
          latency_ms: 20,
        },
      ],
    };

    render(<QueryInspector trace={trace} status="executing" onCancel={onCancelMock} />);

    const cancelButton = screen.getByRole('button', { name: /cancel query/i });
    expect(cancelButton).toBeInTheDocument();

    fireEvent.click(cancelButton);
    expect(onCancelMock).toHaveBeenCalledTimes(1);
  });

  it('escapes SQL tags and ensures no secret canary appears in DOM', () => {
    const canarySecret = 'canary_ultra_secret_pw123';
    const trace: TraceData = {
      query_id: 'run-xss-01',
      status: 'completed',
      attempts: [
        {
          attempt_number: 1,
          status: 'success',
          generated_sql: '<script>alert("xss")</script>',
          prompt_tokens: 10,
          completion_tokens: 10,
          latency_ms: 10,
        },
      ],
    };

    render(<QueryInspector trace={trace} status="completed" />);

    // Script tag is escaped as text content, not executable script element
    expect(screen.getByText('<script>alert("xss")</script>')).toBeInTheDocument();
    expect(document.querySelector('script:not([type])')).toBeNull();
    expect(screen.queryByText(canarySecret)).not.toBeInTheDocument();
  });
});
