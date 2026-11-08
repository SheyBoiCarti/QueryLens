import React, { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { CatalogTable } from '../../api/catalog.ts';
import { CatalogLabelInput, LabelsResponse } from '../../api/generated/schema.ts';

interface LabelManagerProps {
  connectionId: string;
  tables: CatalogTable[];
  onSaved: (labels: LabelsResponse) => void;
  onLoaded?: (labels: LabelsResponse) => void;
}

export function labelFor(labels: CatalogLabelInput[], namespace: string, table: string, column: string | null = null): CatalogLabelInput | undefined {
  return labels.find((label) => label.namespace === namespace && label.table_name === table && (label.column_name ?? null) === column);
}

// A connection change discards the previous connection's draft and invalidates requests.
export function LabelManager(props: LabelManagerProps): React.JSX.Element {
  return <LabelForm key={props.connectionId} {...props} />;
}

function LabelForm({ connectionId, tables, onSaved, onLoaded }: LabelManagerProps): React.JSX.Element {
  const [labels, setLabels] = useState<CatalogLabelInput[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [reload, setReload] = useState(0);
  const mounted = useRef(true);
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError(null);
    api.get<LabelsResponse>(`/api/v1/connections/${connectionId}/labels`, { signal: abort.signal })
      .then((data) => { if (!abort.signal.aborted) { setLabels(data.labels); setVersion(data.semantic_version); onLoadedRef.current?.(data); } })
      .catch((err: unknown) => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : 'Could not load labels'); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [connectionId, reload]);

  const objects = tables.flatMap((table) => [null, ...table.columns.map((column) => column.name)].map((column) => ({
    namespace: table.namespace, table_name: table.name, column_name: column,
  })));
  const update = (object: typeof objects[number], field: 'display_name' | 'description', value: string) => {
    setSaved(false);
    setLabels((current) => {
      const old = labelFor(current, object.namespace, object.table_name, object.column_name);
      return [...current.filter((item) => item !== old), { ...object, display_name: old?.display_name ?? '', description: old?.description ?? null, [field]: value }];
    });
  };
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (version === null) return;
    setSaving(true); setSaved(false); setError(null);
    const visible = objects.flatMap((object) => {
      const label = labelFor(labels, object.namespace, object.table_name, object.column_name);
      return label?.display_name.trim() ? [{ ...object, display_name: label.display_name.trim(), description: label.description?.trim() || null }] : [];
    });
    try {
      const data = await api.put<LabelsResponse>(`/api/v1/connections/${connectionId}/labels`, { expected_semantic_version: version, labels: visible });
      if (!mounted.current) return;
      setVersion(data.semantic_version); setLabels(data.labels); setSaved(true); onSaved(data);
    } catch (err) {
      if (mounted.current) setError(err instanceof ApiError ? `${err.message}${err.statusCode === 409 ? ' Reload labels before retrying; reloading replaces your draft.' : ''}` : 'Could not save labels');
    } finally { if (mounted.current) setSaving(false); }
  };
  return <section className="space-y-3 border rounded bg-white p-4">
    <h3 className="font-semibold">Business labels</h3>
    <p className="text-sm text-slate-600">Add business names and descriptions. Physical names remain visible. Clear a display name to remove its label.</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {loading && <p role="status">Loading labels...</p>}
    {saved && <p role="status">Labels saved.</p>}
    <form onSubmit={(event) => void save(event)} className="space-y-3">
      <fieldset disabled={loading || saving || version === null} className="space-y-3">
        {objects.map((object) => {
          const physical = `${object.namespace}.${object.table_name}${object.column_name === null ? '' : `.${object.column_name}`}`;
          const label = labelFor(labels, object.namespace, object.table_name, object.column_name);
          return <div key={physical} className="grid gap-2 md:grid-cols-3">
            <span className="font-mono text-sm">{physical}</span>
            <label className="text-sm">Display name <input aria-label={`${physical} display name`} maxLength={200} value={label?.display_name ?? ''} onChange={(event) => update(object, 'display_name', event.target.value)} className="border rounded p-2 w-full" /></label>
            <label className="text-sm">Description <input aria-label={`${physical} description`} maxLength={2000} value={label?.description ?? ''} onChange={(event) => update(object, 'description', event.target.value)} className="border rounded p-2 w-full" /></label>
          </div>;
        })}
      </fieldset>
      <div className="flex gap-3">
        <button type="submit" disabled={loading || saving || version === null}>{saving ? 'Saving labels...' : 'Save labels'}</button>
        <button type="button" disabled={loading || saving} onClick={() => { setSaved(false); setReload((value) => value + 1); }}>Reload labels (discard draft)</button>
      </div>
    </form>
  </section>;
}
