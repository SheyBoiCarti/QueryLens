import React, { useEffect, useState } from 'react';
import { api } from '../../api/client.ts';
import { ConnectionResponse } from '../../api/generated/schema.ts';

interface Props {
  connection: ConnectionResponse;
  onDone: () => void;
}

const discoveries = new Map<string, Promise<Record<string, string[]>>>();

function discoverColumns(connectionId: string): Promise<Record<string, string[]>> {
  const pending = discoveries.get(connectionId);
  if (pending) return pending;
  const request = api.get<Record<string, string[]>>(`/api/v1/connections/${connectionId}/schema/discover/columns`)
    .finally(() => discoveries.delete(connectionId));
  discoveries.set(connectionId, request);
  return request;
}

export function VisibilityEditor({ connection, onDone }: Props): React.JSX.Element {
  const [discovered, setDiscovered] = useState<Record<string, string[]>>({});
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [discoveryFailed, setDiscoveryFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setDiscoveryFailed(false);
    setLoading(true);
    setError(null);
    discoverColumns(connection.id)
      .then((tables) => {
        if (!active) return;
        setDiscovered(tables);
        const policy: Record<string, string[]> = {};
        for (const [key, columns] of Object.entries(tables)) {
          const current = connection.allowed_tables?.[key] ?? connection.allowed_tables?.[key.split('.').slice(1).join('.')];
          if (current !== undefined) policy[key] = current.length ? columns.filter((column) => current.includes(column)) : columns;
        }
        setSelected(policy);
      })
      .catch((err: unknown) => {
        if (active) {
          setDiscoveryFailed(true);
          setError(err instanceof Error ? err.message : 'Discovery failed');
        }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [connection, attempt]);

  const toggleTable = (table: string) => setSelected((current) => {
    const next = { ...current };
    if (table in next) delete next[table];
    else next[table] = [...discovered[table]];
    return next;
  });

  const toggleColumn = (table: string, column: string) => setSelected((current) => {
    const values = current[table] || [];
    const next = { ...current, [table]: values.includes(column) ? values.filter((value) => value !== column) : [...values, column] };
    // Empty list means all columns in the backend policy, so remove the table
    // when its last selected column is unchecked.
    if (!next[table].length) delete next[table];
    return next;
  });

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/api/v1/connections/${connection.id}`, { allowed_tables: selected });
      await api.post(`/api/v1/connections/${connection.id}/schema/refresh`);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save selected tables');
    } finally {
      setSaving(false);
    }
  };

  return <section className="space-y-4 rounded-lg border bg-surface p-6">
    <h2 className="text-lg font-semibold">Select tables and columns for {connection.name}</h2>
    <p className="text-sm text-muted">Only selected columns are available to analytics. Leaving every table unchecked disables analytics for this connection.</p>
    {error && <p role="alert" className="text-danger">{error}</p>}
    {!loading && discoveryFailed && <button onClick={() => setAttempt((value) => value + 1)}>Retry discovery</button>}
    {loading ? <p role="status">Discovering table and column names...</p> : (
      <fieldset disabled={saving} className="space-y-3 max-h-[32rem] overflow-y-auto">
        {Object.entries(discovered).map(([table, columns]) => <div key={table} className="border rounded p-3">
          <label className=""><input type="checkbox" checked={table in selected} onChange={() => toggleTable(table)} /> {table}</label>
          <div className="flex flex-wrap gap-4 mt-2">
            {columns.map((column) => <label key={column} className="">
              <input type="checkbox" checked={selected[table]?.includes(column) ?? false} onChange={() => toggleColumn(table, column)} /> {column}
            </label>)}
          </div>
        </div>)}
        {!error && !Object.keys(discovered).length && <p>No selectable tables were found.</p>}
      </fieldset>
    )}
    <div className="flex gap-4">
      <button disabled={loading || saving || discoveryFailed} onClick={() => void save()} className="rounded btn-primary">{saving ? 'Saving...' : 'Save selections'}</button>
      <button disabled={saving} onClick={onDone}>Close</button>
    </div>
  </section>;
}
