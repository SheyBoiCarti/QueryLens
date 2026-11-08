import React, { useState } from 'react';
import { PublicRunCompleted } from '../../api/generated/schema.ts';
import { AccessibleChart } from './charts/AccessibleChart.tsx';
import { plotValues } from './charts/plotValues.ts';
import { ResultsTable } from './ResultsTable.tsx';
import { SQLPanel } from './SQLPanel.tsx';
import { Assumptions } from './Assumptions.tsx';

export interface AnswerPresentationProps {
  run: PublicRunCompleted;
  onRerun?: () => void;
}

export function AnswerPresentation({ run, onRerun }: AnswerPresentationProps): React.JSX.Element {
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');

  const plot = plotValues(run.presentation, run.columns, run.rows || []);
  const canPlot = run.results_available && plot.eligible;

  // Deduplicate warnings
  const warnings = Array.from(new Set([...(run.warnings || []), ...(run.presentation?.warnings || [])]));

  const isExpired = !run.results_available;
  const isSingleValue = !isExpired && run.presentation?.chart_type === 'single_value' && run.presentation?.value != null;

  return (
    <div className="space-y-6" data-testid="answer-presentation">
      {/* 1. Answer Header: Title, KPI / Single Value, Explanation */}
      <div className="space-y-2">
        <h3 className="text-xl font-bold text-slate-900">
          {run.presentation?.title || 'Query Result'}
        </h3>

        {/* Verified Definitions */}
        {run.presentation?.verified_definitions && run.presentation.verified_definitions.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {run.presentation.verified_definitions.map((def) => (
              <span
                key={def.id}
                className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800"
                title={def.description || undefined}
              >
                {def.name}
                {def.units ? ` (${def.units})` : ''}
              </span>
            ))}
          </div>
        )}

        {/* Date Scope */}
        {run.presentation?.date_scope && run.presentation.date_scope.length > 0 && (
          <div className="text-xs text-slate-500">
            Scope:{' '}
            {run.presentation.date_scope
              .map((ds) => `${ds.column.column_name || ds.column.table_name} ${ds.operator} ${ds.value}`)
              .join(', ')}
          </div>
        )}

        {/* Single Value KPI Card */}
        {isSingleValue && (
          <div className="p-4 bg-indigo-50 border border-indigo-100 rounded-lg inline-block">
            <div className="text-3xl font-extrabold text-indigo-700 font-mono tracking-tight" data-testid="kpi-value">
              {run.presentation!.value}
            </div>
            {run.presentation?.units && (
              <span className="text-xs font-medium text-indigo-600 mt-1 block">
                {run.presentation.units}
              </span>
            )}
          </div>
        )}

        {/* Explanation (only shown if not expired) */}
        {!isExpired && run.presentation?.explanation && (
          <p className="text-sm text-slate-600" data-testid="presentation-explanation">
            {run.presentation.explanation}
          </p>
        )}
      </div>

      {/* 2. Visible Warnings Banner */}
      {warnings.length > 0 && (
        <div role="alert" className="bg-amber-50 border border-amber-200 rounded-md p-3 text-xs text-amber-800 space-y-1">
          <span className="font-semibold block">Warnings:</span>
          <ul className="list-disc list-inside space-y-0.5">
            {warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 3. Main Body: Chart vs Table, or Expired Notice */}
      {isExpired ? (
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-6 text-center space-y-4">
          <p role="status" className="text-slate-600 text-sm">
            Results have expired or the connection policy changed. Submit the question again to retrieve fresh results.
          </p>
          {onRerun && (
            <button
              onClick={onRerun}
              className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors shadow-sm"
            >
              Rerun query
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {/* Tab switch between Chart and Table when chart is eligible */}
          {canPlot && (
            <div className="flex border-b border-slate-200" role="tablist" aria-label="Result View Mode">
              <button
                role="tab"
                aria-selected={viewMode === 'chart'}
                id="tab-chart"
                aria-controls="panel-chart"
                onClick={() => setViewMode('chart')}
                className={`py-2 px-4 text-sm font-medium border-b-2 transition-colors ${
                  viewMode === 'chart'
                    ? 'border-indigo-600 text-indigo-600'
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
                }`}
              >
                Chart
              </button>
              <button
                role="tab"
                aria-selected={viewMode === 'table'}
                id="tab-table"
                aria-controls="panel-table"
                onClick={() => setViewMode('table')}
                className={`py-2 px-4 text-sm font-medium border-b-2 transition-colors ${
                  viewMode === 'table'
                    ? 'border-indigo-600 text-indigo-600'
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
                }`}
              >
                Table
              </button>
            </div>
          )}

          {/* View Container */}
          <div className="mt-2">
            {canPlot && viewMode === 'chart' ? (
              <div id="panel-chart" role="tabpanel" aria-labelledby="tab-chart">
                <AccessibleChart presentation={run.presentation} columns={run.columns} rows={run.rows || []} />
              </div>
            ) : (
              <div id="panel-table" role="tabpanel" aria-labelledby="tab-table">
                <ResultsTable columns={run.columns} rows={run.rows || []} truncated={run.truncated} />
              </div>
            )}
          </div>

          {/* CSV Download Link */}
          {run.rows && run.rows.length > 0 && (
            <div className="pt-2">
              <a
                className="text-indigo-700 hover:text-indigo-900 underline text-sm font-medium"
                href={`/api/v1/queries/${run.query_id}/export?format=csv`}
              >
                Download CSV
              </a>
            </div>
          )}
        </div>
      )}

      {/* 4. Collapsed Executed SQL and Assumptions */}
      <details
        className="group border border-slate-200 rounded-lg p-3 bg-slate-50"
        aria-label="Executed SQL"
      >
        <summary className="cursor-pointer font-medium text-sm text-slate-700 hover:text-slate-900 select-none">
          Executed SQL
        </summary>
        <div className="mt-3 space-y-3">
          <SQLPanel sql={run.sql} dialect={run.dialect} />
          {run.assumptions && run.assumptions.length > 0 && (
            <Assumptions assumptions={run.assumptions} />
          )}
        </div>
      </details>
    </div>
  );
}

export default AnswerPresentation;
