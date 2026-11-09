/**
 * Frontend plotting eligibility and numeric safety validation (Contracts C08, C09, Task 4/9).
 */

import { ColumnMeta, PresentationMetadata } from '../../../api/generated/schema.ts';

const NUMERIC_TYPES = new Set(['integer', 'decimal', 'float']);
const KEY_TYPES = new Set(['date', 'datetime', 'string', 'boolean']);
const JS_SAFE_INTEGER = 9007199254740991;

export interface PlotPoint {
  x: string | number;
  y: number;
  label: string;
  originalX: unknown;
  originalY: unknown;
}

export interface PlotData {
  eligible: true;
  chartType: 'line' | 'bar';
  xColumn: string;
  yColumn: string;
  points: PlotPoint[];
  units?: string | null;
}

export interface IneligiblePlot {
  eligible: false;
  reason: string;
}

export type PlotResult = PlotData | IneligiblePlot;

export function plotValues(
  presentation?: PresentationMetadata | null,
  columns: ColumnMeta[] = [],
  rows: Record<string, unknown>[] = []
): PlotResult {
  if (!presentation || presentation.chart_type === 'table' || presentation.chart_type === 'single_value') {
    return { eligible: false, reason: 'Presentation is not a chart' };
  }

  if (columns.length !== 2) {
    return { eligible: false, reason: 'Plotting requires exactly two columns' };
  }

  if (rows.length < 1 || rows.length > 50) {
    return { eligible: false, reason: `Row count (${rows.length}) must be between 1 and 50` };
  }

  let xCol = columns.find((c) => c.name === presentation.x_column);
  let yCol = columns.find((c) => c.name === presentation.y_column);

  if (!xCol || !yCol) {
    const numericCols = columns.filter((c) => NUMERIC_TYPES.has(c.type));
    const nonNumericCols = columns.filter((c) => KEY_TYPES.has(c.type));
    if (numericCols.length === 1 && nonNumericCols.length === 1) {
      yCol = numericCols[0];
      xCol = nonNumericCols[0];
    } else {
      return { eligible: false, reason: 'Columns do not match required numeric and key shapes' };
    }
  }

  if (!KEY_TYPES.has(xCol.type) || !NUMERIC_TYPES.has(yCol.type)) {
    return { eligible: false, reason: 'Key or measure column has ineligible type' };
  }

  const seenKeys = new Set<string>();
  const rawPoints: Array<{ point: PlotPoint; sortKey: number | string }> = [];

  for (let idx = 0; idx < rows.length; idx++) {
    const row = rows[idx];
    const rawX = row[xCol.name];
    const rawY = row[yCol.name];

    if (rawX === null || rawX === undefined || rawX === '') {
      return { eligible: false, reason: 'Key value is empty or null' };
    }

    if (rawY === null || rawY === undefined) {
      return { eligible: false, reason: 'Measure value is null or undefined' };
    }

    // Check key uniqueness and validity
    let keyString = String(rawX);
    let sortKey: number | string = keyString;

    if (xCol.type === 'date' || xCol.type === 'datetime') {
      const parsed = Date.parse(keyString);
      if (Number.isNaN(parsed)) {
        return { eligible: false, reason: `Invalid date key: ${keyString}` };
      }
      keyString = String(parsed); // Normalize instants
      sortKey = parsed;
    } else if (xCol.type === 'boolean') {
      if (typeof rawX !== 'boolean') {
        return { eligible: false, reason: 'Boolean column must contain boolean value' };
      }
    } else if (typeof rawX !== 'string') {
      return { eligible: false, reason: 'String column must contain string value' };
    }

    if (seenKeys.has(keyString)) {
      return { eligible: false, reason: `Duplicate key: ${keyString}` };
    }
    seenKeys.add(keyString);

    // Validate numeric measure
    const yStr = String(rawY).trim();
    const yNum = Number(yStr);

    if (!Number.isFinite(yNum)) {
      return { eligible: false, reason: `Measure is not a finite number: ${rawY}` };
    }

    // Check safe integer bounds
    if (yCol.type === 'integer' || Number.isInteger(yNum)) {
      try {
        const bigIntVal = BigInt(yStr.split('.')[0]);
        if (bigIntVal > BigInt(JS_SAFE_INTEGER) || bigIntVal < BigInt(-JS_SAFE_INTEGER)) {
          return { eligible: false, reason: `Integer exceeds JS safe range: ${rawY}` };
        }
      } catch {
        return { eligible: false, reason: `Invalid integer format: ${rawY}` };
      }
    }

    rawPoints.push({
      point: {
        x: xCol.type === 'date' || xCol.type === 'datetime' ? Number(sortKey) : String(rawX),
        y: yNum,
        label: String(rawX),
        originalX: rawX,
        originalY: rawY,
      },
      sortKey,
    });
  }

  // Row ordering
  let orderedPoints: PlotPoint[];
  if (presentation.plot_row_order && presentation.plot_row_order.length === rows.length) {
    orderedPoints = presentation.plot_row_order.map((i) => rawPoints[i].point);
  } else if (xCol.type === 'date' || xCol.type === 'datetime') {
    orderedPoints = [...rawPoints]
      .sort((a, b) => (a.sortKey as number) - (b.sortKey as number))
      .map((item) => item.point);
  } else {
    orderedPoints = rawPoints.map((item) => item.point);
  }

  const chartType = presentation.chart_type === 'line' || presentation.chart_type === 'bar'
    ? presentation.chart_type
    : xCol.type === 'date' || xCol.type === 'datetime'
      ? 'line'
      : 'bar';

  return {
    eligible: true,
    chartType,
    xColumn: xCol.name,
    yColumn: yCol.name,
    points: orderedPoints,
    units: presentation.units,
  };
}
