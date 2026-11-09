import React, { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { CatalogSnapshot } from '../../api/catalog.ts';
import { FilterOperator, MetricAggregation, MetricDSL, MetricFilter, MetricResponse } from '../../api/generated/schema.ts';

interface MetricEditorProps {
  connectionId: string;
  catalog?: CatalogSnapshot;
  metric?: MetricResponse;
  onSaved: () => void;
  onCancel: () => void;
}
type ValueType = 'string' | 'number' | 'boolean' | 'null';
interface FilterDraft { column: string; operator: FilterOperator; value: string; valueType: ValueType }
const operators: FilterOperator[] = ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in', 'is_null', 'is_not_null'];
const isList = (operator: FilterOperator) => operator === 'in' || operator === 'not_in';
const isNull = (operator: FilterOperator) => operator === 'is_null' || operator === 'is_not_null';
const scalar = (value: unknown): boolean => value === null || typeof value === 'string' || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value));
// Compare exact decimal values, allowing harmless trailing zeros and exponent notation.
// Number()/JSON.parse() alone can round an authored filter before it reaches HTTP.
function normalizedDecimal(lexeme: string): string {
  const [coefficient, exponent = '0'] = lexeme.toLowerCase().split('e');
  const [whole, fraction = ''] = coefficient.replace(/^-/, '').split('.');
  const digits = `${whole}${fraction}`.replace(/^0+/, '');
  if (!digits) return '0';
  const significant = digits.replace(/0+$/, '');
  const power = BigInt(exponent) - BigInt(fraction.length) + BigInt(digits.length - significant.length);
  return `${coefficient.startsWith('-') ? '-' : ''}${significant}e${power}`;
}
function exactNumber(lexeme: string): number {
  const value = Number(lexeme);
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(lexeme) || !Number.isFinite(value)) {
    throw new Error('Enter a finite numeric filter value using decimal notation.');
  }
  if (normalizedDecimal(lexeme) !== normalizedDecimal(value.toString())) {
    throw new Error('Filter number would lose decimal precision. Enter an exactly representable decimal value.');
  }
  return value;
}
const fromFilter = (filter: MetricFilter): FilterDraft => ({ column: filter.column, operator: filter.operator,
  value: typeof filter.value === 'string' && !isList(filter.operator) ? filter.value : JSON.stringify(filter.value ?? null),
  valueType: filter.value === null || filter.value === undefined ? 'null' : typeof filter.value === 'number' ? 'number' : typeof filter.value === 'boolean' ? 'boolean' : 'string' });
function toFilter(filter: FilterDraft): MetricFilter {
  if (isNull(filter.operator)) return { column: filter.column, operator: filter.operator, value: null };
  let value: unknown = filter.value;
  if (isList(filter.operator)) {
    try { value = JSON.parse(filter.value); } catch { throw new Error('Filter lists must be JSON arrays of scalar values.'); }
    if (!Array.isArray(value) || !value.every(scalar)) throw new Error('Filter lists must contain only scalar values.');
    // Match whole JSON strings first so numeric-looking strings stay explicitly strings.
    for (const token of filter.value.matchAll(/"(?:[^"\\]|\\.)*"|(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/g)) {
      if (token[1] !== undefined) exactNumber(token[1]);
    }
  } else if (filter.valueType === 'number') {
    value = exactNumber(filter.value.trim());
  } else if (filter.valueType === 'boolean') {
    if (!['true', 'false'].includes(filter.value)) throw new Error('Select a boolean filter value.');
    value = filter.value === 'true';
  } else if (filter.valueType === 'null') value = null;
  return { column: filter.column, operator: filter.operator, value };
}

export function MetricEditor(props: MetricEditorProps): React.JSX.Element {
  return <MetricForm key={`${props.connectionId}:${props.metric?.id ?? 'new'}`} {...props} />;
}
function MetricForm({ connectionId, catalog, metric, onSaved, onCancel }: MetricEditorProps): React.JSX.Element {
  const initial = metric?.dsl;
  const [key, setKey] = useState(initial?.key ?? '');
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [units, setUnits] = useState(initial?.units ?? '');
  const [synonyms, setSynonyms] = useState((initial?.synonyms ?? []).join('\n'));
  const [table, setTable] = useState(initial?.table ?? '');
  const [measureColumn, setMeasureColumn] = useState(initial?.measure_column ?? '');
  const [aggregation, setAggregation] = useState<MetricAggregation>(initial?.aggregation ?? 'sum');
  const [filters, setFilters] = useState<FilterDraft[]>((initial?.filters ?? []).map(fromFilter));
  const [grain, setGrain] = useState(initial?.grain ?? []);
  const [enabled, setEnabled] = useState(metric?.enabled ?? true);
  const [version, setVersion] = useState(metric?.version ?? 1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const tables = catalog?.connection_id === connectionId ? catalog.tables : [];
  const matches = tables.filter((item) => `${item.namespace}.${item.name}` === table || (!table.includes('.') && item.name === table));
  const selectedTable = matches.length === 1 ? matches[0] : undefined;
  const columns = selectedTable?.columns ?? [];
  const physicalTable = selectedTable ? `${selectedTable.namespace}.${selectedTable.name}` : table;
  const validColumn = (reference: string) => columns.some((column) => [column.name, `${selectedTable?.name}.${column.name}`, `${physicalTable}.${column.name}`].includes(reference));
  const updateFilter = (index: number, patch: Partial<FilterDraft>) => setFilters((current) => current.map((filter, i) => i === index ? { ...filter, ...patch } : filter));
  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault(); setError(null);
    try {
      if (!selectedTable || !columns.some((column) => column.name === measureColumn) || filters.some((filter) => !validColumn(filter.column)) || grain.some((column) => !validColumn(column))) {
        throw new Error('Select a visible table and columns from the current catalog.');
      }
      const dsl: MetricDSL = { key: key.trim(), name: name.trim(), description: description.trim() || null,
        units: units.trim() || null, synonyms: synonyms.split('\n').map((alias) => alias.trim()).filter(Boolean), table,
        measure_column: measureColumn, aggregation, filters: filters.map(toFilter), grain };
      setLoading(true);
      const saved = metric
        ? await api.patch<MetricResponse>(`/api/v1/connections/${connectionId}/metrics/${metric.id}`, { expected_version: version, dsl, enabled })
        : await api.post<MetricResponse>(`/api/v1/connections/${connectionId}/metrics`, dsl);
      if (!mounted.current) return;
      setVersion(saved.version); onSaved();
    } catch (err) {
      if (mounted.current) setError(err instanceof ApiError ? `${err.message}${err.statusCode === 409 ? ' Close and reopen this metric to load its current version; your draft is kept here.' : ''}` : err instanceof Error ? err.message : 'Failed to save metric');
    } finally { if (mounted.current) setLoading(false); }
  };
  const inputClass = 'w-full px-3 py-2 border rounded-md text-sm';
  const columnOptions = (current: string) => <>{current && !columns.some((column) => column.name === current) && <option value={current}>{current}{validColumn(current) ? '' : ' (unavailable)'}</option>}{columns.map((column) => <option key={column.name} value={column.name}>{column.name} ({column.canonical_type})</option>)}</>;
  return <div className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
    <h3 className="text-lg font-bold">{metric ? 'Edit Business Metric' : 'Define Business Metric'}</h3>
    {error && <div role="alert" className="p-3 bg-red-50 text-red-700">{error}</div>}
    <form onSubmit={(event) => void handleSubmit(event)} className="space-y-4">
      <fieldset disabled={loading} className="space-y-4">
        <label className="block">Metric key<input aria-label="Metric key" required pattern="[a-z0-9_]+" maxLength={100} value={key} onChange={(event) => setKey(event.target.value)} className={inputClass} /></label>
        <label className="block">Display name<input aria-label="Display name" required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} className={inputClass} /></label>
        <label className="block">Description<textarea aria-label="Description" maxLength={1000} value={description} onChange={(event) => setDescription(event.target.value)} className={inputClass} /></label>
        <label className="block">Units<input aria-label="Units" maxLength={50} value={units} onChange={(event) => setUnits(event.target.value)} className={inputClass} /></label>
        <label className="block">Synonyms (one per line)<textarea aria-label="Synonyms (one per line)" value={synonyms} onChange={(event) => setSynonyms(event.target.value)} className={inputClass} /></label>
        <label className="block">Table<select aria-label="Table" required value={table} className={inputClass} onChange={(event) => { setTable(event.target.value); setMeasureColumn(''); setFilters([]); setGrain([]); }}>
          <option value="">Choose a physical table</option>
          {table && !tables.some((item) => `${item.namespace}.${item.name}` === table) && <option value={table}>{table}{selectedTable ? '' : ' (unavailable)'}</option>}
          {tables.map((item) => <option key={`${item.namespace}.${item.name}`} value={`${item.namespace}.${item.name}`}>{item.namespace}.{item.name}</option>)}
        </select></label>
        <label className="block">Measure column<select aria-label="Measure column" required value={measureColumn} className={inputClass} onChange={(event) => setMeasureColumn(event.target.value)}>
          <option value="">Choose a physical column</option>{columnOptions(measureColumn)}
        </select></label>
        <label className="block">Aggregation<select aria-label="Aggregation" value={aggregation} onChange={(event) => setAggregation(event.target.value as MetricAggregation)} className={inputClass}>
          {(['sum', 'count', 'count_distinct', 'avg', 'min', 'max'] as const).map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}
        </select></label>
        <fieldset className="border rounded p-3 space-y-2"><legend>Grain (group by physical columns)</legend>
          {grain.filter((column) => !columns.some((item) => item.name === column)).map((column) => <label key={column} className="block"><input type="checkbox" checked onChange={() => setGrain((current) => current.filter((value) => value !== column))} />{column}{validColumn(column) ? '' : ' (unavailable)'}</label>)}
          {columns.map((column) => <label key={column.name} className="block"><input aria-label={`Grain ${column.name}`} type="checkbox" checked={grain.includes(column.name)} onChange={(event) => setGrain((current) => event.target.checked ? [...current, column.name] : current.filter((value) => value !== column.name))} /> {column.name}</label>)}
        </fieldset>
        <fieldset className="border rounded p-3 space-y-3"><legend>Structured filters</legend>
          {filters.map((filter, index) => <div key={index} className="border rounded p-3 space-y-2">
            <label>Column<select aria-label={`Filter ${index + 1} column`} required value={filter.column} onChange={(event) => updateFilter(index, { column: event.target.value })} className={inputClass}><option value="">Choose a physical column</option>{columnOptions(filter.column)}</select></label>
            <label>Operator<select aria-label={`Filter ${index + 1} operator`} value={filter.operator} onChange={(event) => { const operator = event.target.value as FilterOperator; updateFilter(index, { operator, ...(isList(operator) !== isList(filter.operator) ? { value: isList(operator) ? '[]' : '' } : {}) }); }} className={inputClass}>{operators.map((operator) => <option key={operator} value={operator}>{operator}</option>)}</select></label>
            {!isNull(filter.operator) && <>
              {!isList(filter.operator) && <label>Value type<select aria-label={`Filter ${index + 1} value type`} value={filter.valueType} onChange={(event) => { const valueType = event.target.value as ValueType; updateFilter(index, { valueType, value: valueType === 'boolean' ? 'true' : valueType === 'null' ? 'null' : '' }); }} className={inputClass}>{['string', 'number', 'boolean', 'null'].map((type) => <option key={type}>{type}</option>)}</select></label>}
              {isList(filter.operator) ? <label>Values (JSON scalar array)<input aria-label={`Filter ${index + 1} value`} value={filter.value} onChange={(event) => updateFilter(index, { value: event.target.value })} className={inputClass} /></label>
                : filter.valueType === 'boolean' ? <label>Value<select aria-label={`Filter ${index + 1} value`} value={filter.value} onChange={(event) => updateFilter(index, { value: event.target.value })} className={inputClass}><option value="true">true</option><option value="false">false</option></select></label>
                : filter.valueType !== 'null' && <label>Value<input aria-label={`Filter ${index + 1} value`} value={filter.value} onChange={(event) => updateFilter(index, { value: event.target.value })} className={inputClass} /></label>}
            </>}
            <button type="button" onClick={() => setFilters((current) => current.filter((_, i) => i !== index))}>Remove filter {index + 1}</button>
          </div>)}
          <button type="button" disabled={!selectedTable} onClick={() => setFilters((current) => [...current, { column: '', operator: 'eq', value: '', valueType: 'string' }])}>Add filter</button>
        </fieldset>
        {metric && <label className="block"><input aria-label="Metric enabled" type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> Enabled</label>}
      </fieldset>
      <div className="flex justify-end gap-3 pt-4 border-t">
        <button type="button" onClick={onCancel} disabled={loading}>Cancel</button>
        <button type="submit" disabled={loading || !selectedTable}>{loading ? 'Saving...' : 'Save metric'}</button>
      </div>
    </form>
  </div>;
}
export default MetricEditor;
