import React from 'react';

export type NoticeType = 'loading' | 'empty' | 'error' | 'expired' | 'info';

export interface StatusNoticeProps {
  type: NoticeType;
  title?: string;
  message: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export function StatusNotice({
  type,
  title,
  message,
  action,
}: StatusNoticeProps): React.JSX.Element {
  const styles: Record<NoticeType, { bg: string; text: string; border: string }> = {
    loading: { bg: 'bg-subtle', text: 'text-accent', border: 'border-border-control' },
    empty: { bg: 'bg-subtle', text: 'text-text', border: 'border-border' },
    error: { bg: 'bg-surface', text: 'text-danger', border: 'border-danger-border' },
    expired: { bg: 'bg-subtle', text: 'text-muted', border: 'border-border' },
    info: { bg: 'bg-subtle', text: 'text-muted', border: 'border-border' },
  };

  const current = styles[type];

  return (
    <div
      role={type === 'error' ? 'alert' : 'status'}
      className={`p-4 rounded-lg border ${current.bg} ${current.border} ${current.text} flex items-center justify-between`}
      data-testid={`status-notice-${type}`}
    >
      <div className="space-y-1">
        {title && <h4 className="font-semibold text-sm">{title}</h4>}
        <p className="text-xs">{message}</p>
      </div>

      {action && (
        <button
          onClick={action.onClick}
          className="ml-4 border rounded font-medium text-text"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

export default StatusNotice;
