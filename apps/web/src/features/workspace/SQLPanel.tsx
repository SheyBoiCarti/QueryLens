import React, { useEffect, useRef, useState } from 'react';
import { RunOrigin } from '../../api/generated/schema.ts';

export interface SQLPanelProps {
  sql: string;
  dialect?: string;
  assumptions?: string[];
  origin?: RunOrigin;
  runId?: string;
  draftValue?: string;
  onRunSql?: (draft: string) => Promise<void>;
  onDraftChange?: (draft: string) => void;
  disabled?: boolean;
}

export function SQLPanel({
  sql,
  dialect = 'SQL',
  assumptions = [],
  origin,
  runId,
  draftValue,
  onRunSql,
  onDraftChange,
  disabled = false,
}: SQLPanelProps): React.JSX.Element {
  const [copied, setCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(draftValue ?? sql);
  const identity = `${runId ?? ''}:${sql}`;
  const previousIdentity = useRef(identity);

  useEffect(() => {
    if (previousIdentity.current === identity) return;
    previousIdentity.current = identity;
    setDraft(draftValue ?? sql);
    setIsEditing(false);
  }, [sql, runId]);

  useEffect(() => {
    if (draftValue !== undefined) setDraft(draftValue);
  }, [draftValue]);

  const updateDraft = (newDraft: string) => {
    setDraft(newDraft);
    onDraftChange?.(newDraft);
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(isEditing ? draft : sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCancel = () => {
    if (draft !== sql) {
      if (window.confirm('Discard unsaved SQL changes?')) {
        updateDraft(sql);
        setIsEditing(false);
      }
    } else {
      setIsEditing(false);
    }
  };

  const handleRun = async () => {
    if (!onRunSql || disabled || !draft.trim()) return;
    await onRunSql(draft);
  };

  const labelText = origin === 'manual_sql'
    ? 'Edited SQL (Manual)'
    : `${dialect} Generated & Executed`;

  return (
    <div className="bg-slate-900 rounded-lg text-slate-100 p-4 space-y-3 font-mono" data-testid="sql-panel">
      <div className="flex items-center justify-between text-xs text-slate-400 border-b border-slate-800 pb-2">
        <span className="uppercase font-semibold tracking-wider">{labelText}</span>
        <div className="flex items-center space-x-2">
          {!isEditing ? (
            <>
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                disabled={disabled}
                className="px-2.5 py-1 bg-indigo-600 rounded hover:bg-indigo-700 text-white font-sans text-xs transition-colors disabled:opacity-50"
              >
                Edit SQL
              </button>
              <button
                type="button"
                onClick={handleCopy}
                className="px-2.5 py-1 bg-slate-800 rounded hover:bg-slate-700 text-slate-200 transition-colors"
              >
                {copied ? 'Copied!' : 'Copy SQL'}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={handleRun}
                disabled={disabled || !draft.trim()}
                className="px-2.5 py-1 bg-emerald-600 rounded hover:bg-emerald-700 text-white font-sans text-xs font-medium transition-colors disabled:opacity-50"
              >
                Run Edited SQL
              </button>
              <button
                type="button"
                onClick={handleCancel}
                className="px-2.5 py-1 bg-slate-800 rounded hover:bg-slate-700 text-slate-300 font-sans text-xs transition-colors"
              >
                Cancel
              </button>
            </>
          )}
        </div>
      </div>

      {!isEditing ? (
        <pre className="text-sm overflow-x-auto text-emerald-400 whitespace-pre-wrap">{sql}</pre>
      ) : (
        <textarea
          aria-label="SQL Editor"
          value={draft}
          onChange={(e) => updateDraft(e.target.value)}
          disabled={disabled}
          rows={6}
          className="w-full bg-slate-950 text-emerald-400 font-mono text-sm p-3 rounded border border-slate-700 focus:outline-none focus:border-indigo-500 resize-y"
        />
      )}

      {assumptions.length > 0 && (
        <div className="pt-2 border-t border-slate-800 text-xs text-slate-400 space-y-1">
          <span className="font-sans font-medium text-slate-300">Model Assumptions:</span>
          <ul className="list-disc list-inside space-y-0.5">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default SQLPanel;
