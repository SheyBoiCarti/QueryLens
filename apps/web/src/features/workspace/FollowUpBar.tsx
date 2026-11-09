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
      className="p-4 bg-indigo-50/60 border border-indigo-200 rounded-lg space-y-3"
      data-testid="followup-bar"
    >
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center space-x-2">
            <span className="text-xs font-semibold text-indigo-900 uppercase tracking-wider">
              Follow-Up Lineage
            </span>
            <span className="text-xs text-indigo-600 bg-indigo-100 px-2 py-0.5 rounded-full font-mono">
              Parent: {parent.query_id}
            </span>
          </div>
          <p className="text-sm font-medium text-slate-800">
            Following up on: &quot;{parent.question}&quot;
          </p>
        </div>

        <button
          type="button"
          onClick={onStartNewQuestion}
          disabled={disabled || submitting}
          className="px-2.5 py-1 text-xs border border-slate-300 rounded bg-white hover:bg-slate-50 text-slate-700 font-medium transition-colors disabled:opacity-50"
        >
          Start New Question
        </button>
      </div>

      {(referencedObjects.length > 0 || appliedFilters.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600 pt-1">
          <span className="font-medium text-slate-500 mr-1">Inherited scope:</span>
          {referencedObjects.map((ref, idx) => {
            const label = ref.column_name ? `${ref.table_name}.${ref.column_name}` : ref.table_name;
            return (
              <span
                key={`ref-${idx}-${label}`}
                className="px-2 py-0.5 bg-white border border-indigo-200 rounded text-indigo-800 font-mono text-[11px]"
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
                className="px-2 py-0.5 bg-white border border-slate-300 rounded text-slate-700 text-[11px]"
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
          className="flex-1 px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white disabled:bg-slate-100"
          aria-label="Ask a follow-up question"
        />
        <button
          type="submit"
          disabled={!question.trim() || disabled || submitting}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-md text-sm font-medium transition-colors disabled:opacity-50"
        >
          {submitting ? 'Submitting...' : 'Ask Follow-Up'}
        </button>
      </form>
    </div>
  );
}

export default FollowUpBar;
