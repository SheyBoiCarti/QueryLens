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
  onRunSql?: (draft: string) => Promise<void>;
  onDraftChange?: (draft: string) => void;
  draftValue?: string;
  disabled?: boolean;
  onSaveQuestion?: () => void;
  children?: React.ReactNode;
}

export function AnswerPresentation({
  run,
  onRerun,
  onRunSql,
  onDraftChange,
  draftValue,
  disabled = false,
  onSaveQuestion,
  children,
}: AnswerPresentationProps): React.JSX.Element {
  const [viewMode, setViewMode] = useState<'chart' | 'table'>('chart');

  const plot = plotValues(run.presentation, run.columns, run.rows || []);
  const canPlot = run.results_available && plot.eligible;

  // Deduplicate warnings
  const warnings = Array.from(new Set([...(run.warnings || []), ...(run.presentation?.warnings || [])]));

  const isExpired = !run.results_available;
  const isSingleValue = !isExpired && run.presentation?.chart_type === 'single_value' && run.presentation?.value != null;

  return (
    <div className="space-y-4" data-testid="answer-presentation">
      <section className="card table-card">
        {/* 1. Answer Header: Title, KPI / Single Value, Explanation */}
        <div className="table-card-header">
          <div>
            <h2 className="section-title">{run.presentation?.title || 'Query result'}</h2>
            <p className="text-xs text-muted mt-1">{run.results_available ? `${run.rows?.length ?? 0} rows returned` : 'Results unavailable'}</p>
          </div>
          <div className="actions">
            {onSaveQuestion && <button type="button" onClick={onSaveQuestion}>Save as question</button>}
            {run.results_available && !!run.rows?.length && <a className="button" href={`/api/v1/queries/${run.query_id}/export?format=csv`}>Download CSV</a>}
          </div>
        </div>
        <div className="result-body space-y-2">

          {/* Verified Definitions */}
          {run.presentation?.verified_definitions && run.presentation.verified_definitions.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-1">
              {run.presentation.verified_definitions.map((def) => (
                <span
                  key={def.id}
                  className="badge"
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
            <div className="text-xs text-muted">
              Scope:{' '}
              {run.presentation.date_scope
                .map((ds) => `${ds.column.column_name || ds.column.table_name} ${ds.operator} ${ds.value}`)
                .join(', ')}
            </div>
          )}

          {/* Single Value KPI Card */}
          {isSingleValue && (
            <div className="p-4 bg-subtle border border-border-control rounded-lg inline-block">
              <div className="text-lg font-semibold text-text font-mono" data-testid="kpi-value">
                {run.presentation!.value}
              </div>
              {run.presentation?.units && (
                <span className="text-xs font-medium text-muted mt-1 block">
                  {run.presentation.units}
                </span>
              )}
            </div>
          )}

          {/* Explanation (only shown if not expired) */}
          {!isExpired && run.presentation?.explanation && (
            <p className="text-sm text-muted" data-testid="presentation-explanation">
              {run.presentation.explanation}
            </p>
          )}
        </div>

        {/* 2. Visible Warnings Banner */}
        {warnings.length > 0 && (
          <div role="alert" className="bg-subtle border border-border rounded-md p-3 text-xs text-muted space-y-1">
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
          <div className="bg-subtle border border-border rounded-lg p-6 text-center space-y-4">
            <p role="status" className="text-muted text-sm">
              Results have expired or the connection policy changed. Submit the question again to retrieve fresh results.
            </p>
            {onRerun && (
              <button
                onClick={onRerun}
                className="rounded-md font-medium transition-colors btn-primary"
              >
                Rerun query
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {/* Tab switch between Chart and Table when chart is eligible */}
            {canPlot && (
              <div className="flex border-b border-border" role="tablist" aria-label="Result View Mode">
                <button
                  role="tab"
                  aria-selected={viewMode === 'chart'}
                  id="tab-chart"
                  aria-controls="panel-chart"
                  onClick={() => setViewMode('chart')}
                  className={`py-2 px-4 text-sm font-medium border-b-2 transition-colors ${
                    viewMode === 'chart'
                      ? 'border-border-control text-accent'
                      : 'border-transparent text-muted hover:text-text hover:border-border'
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
                      ? 'border-border-control text-accent'
                      : 'border-transparent text-muted hover:text-text hover:border-border'
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

          </div>
        )}
      </section>
      {children}

      {/* Collapsed SQL editor and assumptions */}
      <details
        className="disclosure"
        aria-label="Executed SQL"
      >
        <summary className="cursor-pointer font-medium text-sm text-text hover:text-text select-none">
          Executed SQL
        </summary>
        <div className="mt-3 space-y-3">
          <SQLPanel
            sql={run.sql}
            dialect={run.dialect}
            origin={run.origin}
            runId={run.query_id}
            draftValue={draftValue}
            onRunSql={onRunSql}
            onDraftChange={onDraftChange}
            disabled={disabled}
          />
          {run.assumptions && run.assumptions.length > 0 && (
            <Assumptions assumptions={run.assumptions} />
          )}
        </div>
      </details>
    </div>
  );
}

export default AnswerPresentation;
