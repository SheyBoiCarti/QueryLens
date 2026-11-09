import React, { useId } from 'react';
import { ColumnMeta, PresentationMetadata } from '../../../api/generated/schema.ts';
import { plotValues } from './plotValues.ts';

export interface AccessibleChartProps {
  presentation?: PresentationMetadata | null;
  columns: ColumnMeta[];
  rows: Record<string, unknown>[];
  className?: string;
}

export function AccessibleChart({
  presentation,
  columns,
  rows,
  className = '',
}: AccessibleChartProps): React.JSX.Element | null {
  const chartId = useId();
  const plot = plotValues(presentation, columns, rows);

  if (!plot.eligible) {
    return null;
  }

  const { points, chartType, units } = plot;
  const title = presentation?.title || 'Data chart';

  // SVG dimensions
  const width = 600;
  const height = 280;
  const paddingLeft = 60;
  const paddingRight = 30;
  const paddingTop = 30;
  const paddingBottom = 50;

  const innerWidth = width - paddingLeft - paddingRight;
  const innerHeight = height - paddingTop - paddingBottom;

  const yValues = points.map((p) => p.y);
  const minY = Math.min(0, ...yValues);
  const maxY = Math.max(0, ...yValues) || 1;
  const yRange = maxY - minY || 1;

  const scaleY = (val: number) => {
    return paddingTop + innerHeight - ((val - minY) / yRange) * innerHeight;
  };

  const temporal = points.length > 0 && typeof points[0].x === 'number';
  const temporalValues = temporal ? points.map((point) => point.x as number) : [];
  const temporalMin = Math.min(...temporalValues);
  const temporalMax = Math.max(...temporalValues);
  const scaleX = (idx: number) => {
    if (points.length === 1) return paddingLeft + innerWidth / 2;
    if (temporal && temporalMax > temporalMin) {
      return paddingLeft + (((points[idx].x as number) - temporalMin) / (temporalMax - temporalMin)) * innerWidth;
    }
    return paddingLeft + (idx / (points.length - 1)) * innerWidth;
  };

  const barWidth = Math.min(40, (innerWidth / points.length) * 0.7);

  // Line path
  const linePath = points
    .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${scaleX(idx)} ${scaleY(p.y)}`)
    .join(' ');

  return (
    <div className={`bg-white rounded-lg border border-slate-200 p-4 ${className}`} data-testid="accessible-chart">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-semibold text-slate-800">{title}</h4>
        {units && <span className="text-xs text-slate-500 font-medium">Units: {units}</span>}
      </div>

      <div className="relative overflow-x-auto">
        <svg
          role="img"
          aria-labelledby={`chart-title-${chartId} chart-desc-${chartId}`}
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-auto max-h-[350px] overflow-visible"
        >
          <title id={`chart-title-${chartId}`}>{title}</title>
          <desc id={`chart-desc-${chartId}`}>
            {`Chart showing ${points.length} points for ${title}.`}
          </desc>

          {/* Grid lines and Y axis ticks */}
          <line
            x1={paddingLeft}
            y1={scaleY(minY)}
            x2={width - paddingRight}
            y2={scaleY(minY)}
            stroke="#e2e8f0"
            strokeWidth="1"
          />
          <line
            x1={paddingLeft}
            y1={scaleY(maxY)}
            x2={width - paddingRight}
            y2={scaleY(maxY)}
            stroke="#e2e8f0"
            strokeWidth="1"
            strokeDasharray="4 4"
          />

          <text
            x={paddingLeft - 10}
            y={scaleY(maxY) + 4}
            textAnchor="end"
            fontSize="10"
            fill="#64748b"
            fontFamily="monospace"
          >
            {maxY}
          </text>
          <text
            x={paddingLeft - 10}
            y={scaleY(minY) + 4}
            textAnchor="end"
            fontSize="10"
            fill="#64748b"
            fontFamily="monospace"
          >
            {minY}
          </text>

          {/* Chart content: Bar or Line */}
          {chartType === 'bar' ? (
            points.map((p, idx) => {
              const xPos = paddingLeft + (idx + 0.5) * (innerWidth / points.length) - barWidth / 2;
              const yPos = scaleY(Math.max(0, p.y));
              const barHeight = Math.abs(scaleY(p.y) - scaleY(0));
              const labelText = `${p.label}: ${p.originalY}${units ? ' ' + units : ''}`;

              return (
                <g key={idx}>
                  <rect
                    role="graphics-symbol"
                    tabIndex={0}
                    aria-label={labelText}
                    x={xPos}
                    y={yPos}
                    width={barWidth}
                    height={Math.max(2, barHeight)}
                    fill="#6366f1"
                    rx="2"
                    className="hover:fill-indigo-700 focus:fill-indigo-700 transition-colors cursor-pointer outline-none"
                  >
                    <title>{labelText}</title>
                  </rect>
                  <text
                    x={xPos + barWidth / 2}
                    y={height - paddingBottom + 16}
                    textAnchor="middle"
                    fontSize="10"
                    fill="#475569"
                    className="truncate"
                  >
                    {p.label.length > 10 ? `${p.label.slice(0, 8)}…` : p.label}
                  </text>
                </g>
              );
            })
          ) : (
            <>
              <path
                d={linePath}
                fill="none"
                stroke="#6366f1"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {points.map((p, idx) => {
                const cx = scaleX(idx);
                const cy = scaleY(p.y);
                const labelText = `${p.label}: ${p.originalY}${units ? ' ' + units : ''}`;

                return (
                  <g key={idx}>
                    <circle
                      role="graphics-symbol"
                      tabIndex={0}
                      aria-label={labelText}
                      cx={cx}
                      cy={cy}
                      r="4.5"
                      fill="#ffffff"
                      stroke="#4f46e5"
                      strokeWidth="2.5"
                      className="hover:r-6 focus:r-6 transition-all cursor-pointer outline-none"
                    >
                      <title>{labelText}</title>
                    </circle>
                    <text
                      x={cx}
                      y={height - paddingBottom + 16}
                      textAnchor="middle"
                      fontSize="10"
                      fill="#475569"
                    >
                      {p.label.length > 10 ? `${p.label.slice(0, 8)}…` : p.label}
                    </text>
                  </g>
                );
              })}
            </>
          )}
        </svg>
      </div>

      {/* Screen-reader accessible data table */}
      <div className="sr-only">
        <table>
          <caption>{title}</caption>
          <thead>
            <tr>
              <th scope="col">{plot.xColumn}</th>
              <th scope="col">{plot.yColumn} {units ? `(${units})` : ''}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p, idx) => (
              <tr key={idx}>
                <td>{String(p.originalX)}</td>
                <td>{String(p.originalY)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default AccessibleChart;
