import React, { useState } from 'react';
import { PublicRunCompleted } from '../../api/generated/schema.ts';

export interface FollowUpBarProps {
  parent: PublicRunCompleted;
  onSubmit: (question: string, parentQueryId: string) => Promise<void> | void;
  onStartNewQuestion: () => void;
  disabled?: boolean;
}

export function FollowUpBar({
  parent,
  onSubmit,
  onStartNewQuestion,
  disabled = false,
}: FollowUpBarProps): React.JSX.Element {
  const [question, setQuestion] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || disabled || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit(trimmed, parent.query_id);
      // Keep submitted text available if execution later fails.
    } catch {
      // The workspace displays the error; retain the draft.
    } finally {
      setSubmitting(false);
    }
  };

  const context = parent.context;
  const referencedObjects = context?.referenced_objects || [];
  const appliedFilters = context?.applied_filters || [];

  return (
    <div
      className="card followup-card space-y-4"
      data-testid="followup-bar"
    >
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-text">
              Follow-up lineage
            </span>
            <span className="text-xs text-muted font-mono break-all">
              Parent: {parent.query_id}
            </span>
          </div>
          <p className="text-sm font-medium text-text">
            Following up on: &quot;{parent.question}&quot;
          </p>
        </div>

        <button
          type="button"
          onClick={onStartNewQuestion}
          disabled={disabled || submitting}
          className="border rounded text-text font-medium transition-colors"
        >
          Start new question
        </button>
      </div>

      {(referencedObjects.length > 0 || appliedFilters.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted pt-1">
          <span className="font-medium text-muted mr-1">Inherited scope:</span>
          {referencedObjects.map((ref, idx) => {
            const label = ref.column_name ? `${ref.table_name}.${ref.column_name}` : ref.table_name;
            return (
              <span
                key={`ref-${idx}-${label}`}
                className="badge font-mono"
              >
                {label}
              </span>
            );
          })}
          {appliedFilters.map((flt, idx) => {
            const colName = flt.column?.column_name
              ? `${flt.column.table_name}.${flt.column.column_name}`
              : typeof flt.column === 'string'
              ? flt.column
              : flt.column?.table_name || 'column';
            const valStr = Array.isArray(flt.value)
              ? flt.value.join(', ')
              : flt.value !== undefined
              ? String(flt.value)
              : '';
            return (
              <span
                key={`flt-${idx}-${colName}`}
                className="badge"
              >
                {colName} {flt.operator} {valStr}
              </span>
            );
          })}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a follow-up question..."
          disabled={disabled || submitting}
          className="flex-1 border rounded-md disabled:bg-subtle"
          aria-label="Ask a follow-up question"
        />
        <button
          type="submit"
          disabled={!question.trim() || disabled || submitting}
          className="btn-primary"
        >
          {submitting ? 'Submitting...' : 'Ask follow-up'}
        </button>
      </form>
    </div>
  );
}

export default FollowUpBar;
