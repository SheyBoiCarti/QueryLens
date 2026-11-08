import { ParameterDefinition, DateRangeInput } from '../../api/generated/schema.ts';

export interface SavedQuestionFiltersProps {
  parameters: ParameterDefinition[];
  values: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
  onRun: () => void;
  disabled?: boolean;
}

export function SavedQuestionFilters({
  parameters,
  values,
  onChange,
  onRun,
  disabled = false,
}: SavedQuestionFiltersProps): React.JSX.Element {
  if (!parameters || parameters.length === 0) {
    return (
      <div className="flex justify-end pt-2">
        <button
          type="button"
          onClick={onRun}
          disabled={disabled}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
        >
          Run Saved Question
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4 bg-slate-50 border border-slate-200 rounded-lg p-4" data-testid="saved-question-filters">
      <div className="border-b border-slate-200 pb-2">
        <h4 className="text-sm font-semibold text-slate-800">Typed Filter Controls</h4>
        <p className="text-xs text-slate-500">Configure parameters for direct rerun without natural-language latency.</p>
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
                  className="block text-xs font-semibold text-slate-700"
                >
                  {param.label}
                </label>
                {param.target && (
                  <span className="text-[10px] text-slate-400 font-mono block">
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
                          mode: 'fixed',
                          start_date: (dateVal as any).start_date || '2026-01-01',
                          end_date_inclusive: (dateVal as any).end_date_inclusive || '2026-01-31',
                        });
                      } else {
                        onChange(param.name, { mode });
                      }
                    }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm bg-white"
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
                        value={(dateVal as any).start_date || ''}
                        disabled={disabled}
                        onChange={(e) =>
                          onChange(param.name, {
                            ...(dateVal as any),
                            mode: 'fixed',
                            start_date: e.target.value,
                          })
                        }
                        className="px-2 py-1 border border-slate-300 rounded text-xs"
                      />
                      <span className="text-xs text-slate-400">to</span>
                      <input
                        type="date"
                        aria-label={`${param.label} End Date`}
                        value={(dateVal as any).end_date_inclusive || ''}
                        disabled={disabled}
                        onChange={(e) =>
                          onChange(param.name, {
                            ...(dateVal as any),
                            mode: 'fixed',
                            end_date_inclusive: e.target.value,
                          })
                        }
                        className="px-2 py-1 border border-slate-300 rounded text-xs"
                      />
                    </div>
                  )}

                  <span className="text-[11px] text-slate-500 block">
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
                  className="block text-xs font-semibold text-slate-700"
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
                  onChange={(e) => onChange(param.name, Math.max(1, Math.min(1000, Number(e.target.value) || 1)))}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm bg-white"
                />
                <span className="text-[11px] text-slate-500 block">
                  Configured maximum: 1,000 rows
                </span>
              </div>
            );
          }

          // Category parameter
          const choices = param.allowed_values;
          return (
            <div key={param.slot_id} className="space-y-1">
              <label
                htmlFor={`param-${param.name}`}
                className="block text-xs font-semibold text-slate-700"
              >
                {param.label}
              </label>
              {param.target && (
                <span className="text-[10px] text-slate-400 font-mono block">
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
                    // Preserve original types (numbers as numbers, booleans as booleans)
                    const originalChoice = choices.find((c) => String(c) === rawVal);
                    onChange(param.name, originalChoice !== undefined ? originalChoice : rawVal);
                  }}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm bg-white"
                >
                  {choices.map((c, cIdx) => (
                    <option key={cIdx} value={String(c)}>
                      {String(c)}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id={`param-${param.name}`}
                  type="text"
                  value={val !== undefined ? String(val) : String(param.default_value ?? '')}
                  disabled={disabled}
                  onChange={(e) => onChange(param.name, e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm bg-white"
                />
              )}
            </div>
          );
        })}
      </div>

      <div className="flex justify-end pt-2 border-t border-slate-200">
        <button
          type="button"
          onClick={onRun}
          disabled={disabled}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
        >
          Run with Filters
        </button>
      </div>
    </div>
  );
}

export default SavedQuestionFilters;
