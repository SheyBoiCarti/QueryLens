import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import SQLPanel from '../features/workspace/SQLPanel.tsx';
import Assumptions from '../features/workspace/Assumptions.tsx';

describe('SQLPanel and Assumptions (Task 08.04)', () => {
  it('copies exact executed SQL to clipboard', async () => {
    const executedSql = 'SELECT id, email FROM customers WHERE active = true';
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<SQLPanel sql={executedSql} dialect="postgresql" />);

    const copyBtn = screen.getByRole('button', { name: /copy sql/i });
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith(executedSql);
  });

  it('renders SQL as read-only text without arbitrary edit inputs or run buttons', () => {
    render(<SQLPanel sql="SELECT 1" dialect="mysql" />);

    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('button', { name: /run|execute/i })).toBeNull();
    expect(screen.getByText('SELECT 1')).toBeInTheDocument();
  });

  it('escapes malicious metadata and renders as safe text in assumptions and warnings', () => {
    const maliciousAssumptions = ['<script>alert("xss")</script>', '<img src=x onerror=alert(1)>'];
    const maliciousWarnings = ['<div onclick="evil()">click me</div>'];

    render(
      <Assumptions
        assumptions={maliciousAssumptions}
        warnings={maliciousWarnings}
        clarificationQuestion="<script>alert(1)</script>"
      />
    );

    // Rendered as text nodes, not DOM HTML tags
    expect(screen.getByText('<script>alert("xss")</script>')).toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument();
    expect(document.querySelector('script:not([type])')).toBeNull();
  });

  it('identifies expired results with actionable notice', () => {
    render(<Assumptions resultsExpired={true} />);
    expect(screen.getByRole('status')).toHaveTextContent(/Cached query results have expired/);
  });
});
