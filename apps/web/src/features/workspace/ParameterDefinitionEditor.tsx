import { useState } from 'react';
import { ParameterDefinition } from '../../api/generated/schema.ts';
import { SavedQuestionFilters } from './SavedQuestionFilters.tsx';

interface Props {
  parameters: ParameterDefinition[];
  onChange: (parameters: ParameterDefinition[]) => void;
  selectedSlots: Set<string>;
  onSelectionChange: (slots: Set<string>) => void;
  onValidityChange: (valid: boolean) => void;
}

export function ParameterDefinitionEditor({ parameters, onChange, selectedSlots, onSelectionChange, onValidityChange }: Props) {
  const [choiceDrafts, setChoiceDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const update = (index: number, changes: Partial<ParameterDefinition>) =>
    onChange(parameters.map((parameter, i) => i === index ? { ...parameter, ...changes } : parameter));

  return <div className="space-y-4">
    {parameters.map((parameter, index) => <fieldset key={parameter.slot_id} className="border rounded p-3 space-y-2">
      <legend>{parameter.label}</legend>
      <label className="block">
        <input type="checkbox" checked={selectedSlots.has(parameter.slot_id)} onChange={(event) => {
          const next = new Set(selectedSlots);
          if (event.target.checked) next.add(parameter.slot_id); else next.delete(parameter.slot_id);
          onSelectionChange(next);
        }} /> Expose {parameter.name} filter
      </label>
      <label className="block">Display label
        <input aria-label={`${parameter.name} display label`} value={parameter.label}
          onChange={(event) => update(index, { label: event.target.value })} className="w-full border rounded" />
      </label>
      <p className="text-xs">Default selection</p>
      <SavedQuestionFilters parameters={[parameter]} values={{ [parameter.name]: parameter.default_value }}
        onChange={(_, value) => update(index, { default_value: value })} />
      {parameter.param_type === 'category' && <label className="block">Allowed choices (one per line; blank allows typed entry)
        <textarea aria-label={`${parameter.name} allowed choices`}
          value={choiceDrafts[parameter.slot_id] ?? parameter.allowed_values?.map(String).join('\n') ?? ''}
          onChange={(event) => {
            const raw = event.target.value;
            setChoiceDrafts((previous) => ({ ...previous, [parameter.slot_id]: raw }));
            const nextErrors = { ...errors };
            try {
              const choices = raw.trim() ? raw.split('\n').map((part) => {
                if (parameter.source_type === 'string') return part;
                if (parameter.source_type === 'boolean') {
                  if (part === 'true' || part === 'false') return part === 'true';
                  throw new Error('Use true or false for boolean choices.');
                }
                const number = Number(part);
                if (!part.trim() || !Number.isFinite(number) || (parameter.source_type === 'integer' && !Number.isSafeInteger(number))) {
                  throw new Error('Enter a valid number on each line.');
                }
                return number;
              }) : null;
              update(index, { allowed_values: choices });
              delete nextErrors[parameter.slot_id];
            } catch (error) {
              nextErrors[parameter.slot_id] = error instanceof Error ? error.message : 'Invalid choices';
            }
            setErrors(nextErrors);
            onValidityChange(Object.keys(nextErrors).length === 0);
          }} className="w-full border rounded" />
      </label>}
      {errors[parameter.slot_id] && <p role="alert">{errors[parameter.slot_id]}</p>}
    </fieldset>)}
  </div>;
}
