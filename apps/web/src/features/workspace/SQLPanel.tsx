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
    <div className="bg-surface rounded-lg text-text p-4 space-y-3 font-mono" data-testid="sql-panel">
      <div className="flex items-center justify-between text-xs text-dim border-b border-border pb-2">
        <span className="font-semibold">{labelText}</span>
        <div className="flex items-center space-x-2">
          {!isEditing ? (
            <>
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                disabled={disabled}
                className="rounded font-sans transition-colors btn-primary"
              >
                Edit SQL
              </button>
              <button
                type="button"
                onClick={handleCopy}
                className="bg-control rounded hover:bg-active text-text transition-colors"
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
                className="rounded font-sans font-medium transition-colors btn-primary"
              >
                Run edited SQL
              </button>
              <button
                type="button"
                onClick={handleCancel}
                className="bg-control rounded hover:bg-active text-dim font-sans transition-colors"
              >
                Cancel
              </button>
            </>
          )}
        </div>
      </div>

      {!isEditing ? (
        <pre className="text-sm overflow-x-auto text-accent whitespace-pre-wrap">{sql}</pre>
      ) : (
        <textarea
          aria-label="SQL Editor"
          value={draft}
          onChange={(e) => updateDraft(e.target.value)}
          disabled={disabled}
          rows={6}
          className="w-full text-accent font-mono rounded border resize-y"
        />
      )}

      {assumptions.length > 0 && (
        <div className="pt-2 border-t border-border text-xs text-dim space-y-1">
          <span className="font-sans font-medium text-dim">Model assumptions:</span>
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
