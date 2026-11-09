import { ParameterDefinition, DateRangeInput } from '../../api/generated/schema.ts';

export interface SavedQuestionFiltersProps {
  parameters: ParameterDefinition[];
  values: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
  onRun?: () => void;
  disabled?: boolean;
}

export function SavedQuestionFilters({
  parameters,
  values,
  onChange,
  onRun,
  disabled = false,
}: SavedQuestionFiltersProps): React.JSX.Element {
  const fixedDate = (value: DateRangeInput): Extract<DateRangeInput, { mode: 'fixed' }> =>
    value.mode === 'fixed' ? value : { mode: 'fixed', start_date: '2026-01-01', end_date_inclusive: '2026-01-31' };
  if (!parameters || parameters.length === 0) {
    return (
      <div className="flex justify-end pt-2">
        {onRun && <button
          type="button"
          onClick={onRun}
          disabled={disabled}
          className="rounded-md font-medium transition-colors btn-primary"
        >
          Run Saved Question
        </button>}
      </div>
    );
  }

  return (
    <div className="space-y-4 bg-subtle border border-border rounded-lg p-4" data-testid="saved-question-filters">
      <div className="border-b border-border pb-2">
        <h4 className="text-sm font-semibold text-text">Typed Filter Controls</h4>
        <p className="text-xs text-muted">Configure parameters for direct rerun without natural-language latency.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {parameters.map((param) => {
          const val = values[param.name];

          if (param.param_type === 'date_range') {
            const dateVal = (val && typeof val === 'object' ? val : { mode: 'this_month' }) as DateRangeInput;
            const currentMode = dateVal.mode || 'this_month';

            return (
              <div key={param.slot_id} className="space-y-1">
                <label
                  htmlFor={`date-preset-${param.name}`}
                  className="block text-xs"
                >
                  {param.label}
                </label>
                {param.target && (
                  <span className="text-[10px] text-dim font-mono block">
                    {param.target.table_name}.{param.target.column_name} ({param.target.operator})
                  </span>
                )}
                <div className="space-y-2">
                  <select
                    id={`date-preset-${param.name}`}
                    aria-label={`${param.label} Preset`}
                    value={currentMode}
                    disabled={disabled}
                    onChange={(e) => {
                      const mode = e.target.value as 'this_month' | 'this_year' | 'fixed';
                      if (mode === 'fixed') {
                        onChange(param.name, {
                          ...fixedDate(dateVal),
                        });
                      } else {
                        onChange(param.name, { mode });
                      }
                    }}
                    className="w-full border rounded"
                  >
                    <option value="this_month">This Month</option>
                    <option value="this_year">This Year</option>
                    <option value="fixed">Custom Date Range</option>
                  </select>

                  {currentMode === 'fixed' && (
                    <div className="flex items-center space-x-2 pt-1">
                      <input
                        type="date"
                        aria-label={`${param.label} Start Date`}
                        value={dateVal.mode === 'fixed' ? dateVal.start_date : ''}
                        disabled={disabled}
                        onChange={(e) =>
                          onChange(param.name, {
                            ...fixedDate(dateVal),
                            mode: 'fixed',
                            start_date: e.target.value,
                          })
                        }
                        className="border rounded"
                      />
                      <span className="text-xs text-dim">to</span>
                      <input
                        type="date"
                        aria-label={`${param.label} End Date`}
                        value={dateVal.mode === 'fixed' ? dateVal.end_date_inclusive : ''}
                        disabled={disabled}
                        onChange={(e) =>
                          onChange(param.name, {
                            ...fixedDate(dateVal),
                            mode: 'fixed',
                            end_date_inclusive: e.target.value,
                          })
                        }
                        className="border rounded"
                      />
                    </div>
                  )}

                  <span className="text-[11px] text-muted block">
                    Inclusive end-date UTC resolution
                  </span>
                </div>
              </div>
            );
          }

          if (param.param_type === 'result_count') {
            const countVal = typeof val === 'number' ? val : (param.default_value as number) || 100;

            return (
              <div key={param.slot_id} className="space-y-1">
                <label
                  htmlFor={`param-${param.name}`}
                  className="block text-xs"
                >
                  {param.label}
                </label>
                <input
                  id={`param-${param.name}`}
                  type="number"
                  min={1}
                  max={1000}
                  value={countVal}
                  disabled={disabled}
                  onChange={(e) => {
                    const number = Number(e.target.value);
                    if (e.target.value && Number.isSafeInteger(number) && number >= 1 && number <= 1000) onChange(param.name, number);
                  }}
                  className="w-full border rounded"
                />
                <span className="text-[11px] text-muted block">
                  Configured maximum: 1,000 rows
                </span>
              </div>
            );
          }

          // Category parameter
          const choices = param.allowed_values;
          const numeric = param.source_type === 'integer' || param.source_type === 'float' || param.source_type === 'decimal';
          const boolean = param.source_type === 'boolean';
          return (
            <div key={param.slot_id} className="space-y-1">
              <label
                htmlFor={`param-${param.name}`}
                className="block text-xs"
              >
                {param.label}
              </label>
              {param.target && (
                <span className="text-[10px] text-dim font-mono block">
                  {param.target.table_name}.{param.target.column_name} ({param.target.operator})
                </span>
              )}
              {choices && choices.length > 0 ? (
                <select
                  id={`param-${param.name}`}
                  value={val !== undefined ? String(val) : String(param.default_value ?? '')}
                  disabled={disabled}
                  onChange={(e) => {
                    const rawVal = e.target.value;
                    const originalChoice = choices.find((choice) => String(choice) === rawVal && (
                      (param.source_type === 'string' && typeof choice === 'string')
                      || (param.source_type === 'integer' && typeof choice === 'number' && Number.isInteger(choice))
                      || ((param.source_type === 'float' || param.source_type === 'decimal') && typeof choice === 'number')
                      || (param.source_type === 'boolean' && typeof choice === 'boolean')
                    ));
                    if (originalChoice !== undefined) {
                      onChange(param.name, originalChoice);
                    } else if (param.source_type === 'string') {
                      onChange(param.name, rawVal);
                    } else if (numeric) {
                      const parsed = Number(rawVal);
                      if (Number.isFinite(parsed) && (param.source_type !== 'integer' || Number.isInteger(parsed))) onChange(param.name, parsed);
                    }
                  }}
                  className="w-full border rounded"
                >
                  {choices.map((c, cIdx) => (
                    <option key={cIdx} value={String(c)}>
                      {String(c)}
                    </option>
                  ))}
                </select>
              ) : boolean ? (
                <select
                  id={`param-${param.name}`}
                  value={typeof val === 'boolean' ? String(val) : String(param.default_value ?? true)}
                  disabled={disabled}
                  onChange={(e) => onChange(param.name, e.target.value === 'true')}
                  className="w-full border rounded"
                >
                  <option value="true">True</option><option value="false">False</option>
                </select>
              ) : numeric ? (
                <input
                  id={`param-${param.name}`}
                  type="number"
                  step={param.source_type === 'integer' ? 1 : 'any'}
                  value={typeof val === 'number' ? val : (typeof param.default_value === 'number' ? param.default_value : '')}
                  disabled={disabled}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (!value) return;
                    const number = Number(value);
                    if (Number.isFinite(number) && (param.source_type !== 'integer' || Number.isSafeInteger(number))) onChange(param.name, number);
                  }}
                  className="w-full border rounded"
                />
              ) : (
                <input
                  id={`param-${param.name}`}
                  type="text"
                  value={val !== undefined ? String(val) : String(param.default_value ?? '')}
                  disabled={disabled}
                  onChange={(e) => onChange(param.name, e.target.value)}
                  className="w-full border rounded"
                />
              )}
            </div>
          );
        })}
      </div>

      {onRun && <div className="flex justify-end pt-2 border-t border-border">
        <button
          type="button"
          onClick={onRun}
          disabled={disabled}
          className="rounded-md font-medium transition-colors btn-primary"
        >
          Run with Filters
        </button>
      </div>}
    </div>
  );
}

export default SavedQuestionFilters;
