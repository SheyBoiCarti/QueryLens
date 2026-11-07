import React, { useState } from 'react';

interface SQLPanelProps {
  sql: string;
  dialect?: string;
  assumptions?: string[];
}

export function SQLPanel({ sql, dialect = 'SQL', assumptions = [] }: SQLPanelProps): React.JSX.Element {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-slate-900 rounded-lg text-slate-100 p-4 space-y-3 font-mono">
      <div className="flex items-center justify-between text-xs text-slate-400 border-b border-slate-800 pb-2">
        <span className="uppercase font-semibold tracking-wider">{dialect} Generated &amp; Executed</span>
        <button
          onClick={handleCopy}
          className="px-2.5 py-1 bg-slate-800 rounded hover:bg-slate-700 text-slate-200 transition-colors"
        >
          {copied ? 'Copied!' : 'Copy SQL'}
        </button>
      </div>

      <pre className="text-sm overflow-x-auto text-emerald-400 whitespace-pre-wrap">{sql}</pre>

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
