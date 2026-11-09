import TableDetails from './TableDetails.tsx';
import React, { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { CatalogTable } from '../../api/catalog.ts';
import { CatalogLabelInput, LabelsResponse } from '../../api/generated/schema.ts';

interface LabelManagerProps {
  connectionId: string;
  tables: CatalogTable[];
  selectedTable?: CatalogTable | null;
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

function LabelForm({ connectionId, tables, selectedTable, onSaved, onLoaded }: LabelManagerProps): React.JSX.Element {
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
  return <section className="card table-card">
    {error && <p role="alert" className="text-danger p-4">{error}</p>}
    {loading && <p role="status" className="p-4 text-muted">Loading labels...</p>}
    {saved && <p role="status" className="p-4 text-accent">Labels saved.</p>}
    <form onSubmit={(event) => void save(event)}>
      <fieldset disabled={loading || saving || version === null}>
        {(selectedTable === undefined ? tables : selectedTable ? [selectedTable] : []).map((table) => (
          <TableDetails key={`${table.namespace}.${table.name}`} table={table} labels={labels}
            disabled={loading || saving || version === null}
            onLabelChange={(column, field, value) => update({ namespace: table.namespace, table_name: table.name, column_name: column }, field, value)} />
        ))}
      </fieldset>
      <div className="table-card-footer">
        <p>Add business names and descriptions. Clear a display name to remove its label.</p>
        <div className="actions">
          <button type="button" className="btn-link" disabled={loading || saving} onClick={() => { setSaved(false); setReload((value) => value + 1); }}>Reload labels (discard draft)</button>
          <button type="submit" className="btn-primary" disabled={loading || saving || version === null}>{saving ? 'Saving labels...' : 'Save labels'}</button>
        </div>
      </div>
    </form>
  </section>;
}
