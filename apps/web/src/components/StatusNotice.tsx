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
    loading: { bg: 'bg-indigo-50', text: 'text-indigo-800', border: 'border-indigo-200' },
    empty: { bg: 'bg-slate-50', text: 'text-slate-700', border: 'border-slate-200' },
    error: { bg: 'bg-rose-50', text: 'text-rose-800', border: 'border-rose-200' },
    expired: { bg: 'bg-amber-50', text: 'text-amber-800', border: 'border-amber-200' },
    info: { bg: 'bg-sky-50', text: 'text-sky-800', border: 'border-sky-200' },
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
          className="ml-4 px-3 py-1.5 bg-white border border-slate-300 rounded text-xs font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

export default StatusNotice;
