import React from 'react';

interface ColumnMeta {
  name: string;
  canonical_type: string;
  db_type: string;
  nullable: boolean;
  primary_key: boolean;
  comment?: string | null;
}

interface ForeignKeyMeta {
  name?: string | null;
  source_columns: string[];
  target_table: string;
  target_columns: string[];
  cardinality: string;
}

interface TableDetailsProps {
  table: {
    name: string;
    namespace: string;
    columns: ColumnMeta[];
    primary_key_columns: string[];
    foreign_keys: ForeignKeyMeta[];
  };
}

export function TableDetails({ table }: TableDetailsProps): React.JSX.Element {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-6 space-y-6">
      <div>
        <div className="flex items-center space-x-2">
          <h3 className="text-xl font-bold text-slate-900">{table.name}</h3>
          <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-mono">
            {table.namespace}
          </span>
        </div>
      </div>

      <div>
        <h4 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">Columns</h4>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-slate-600 font-medium">
              <tr>
                <th className="py-2 px-3">Name</th>
                <th className="py-2 px-3">Type</th>
                <th className="py-2 px-3">Native DB Type</th>
                <th className="py-2 px-3">Key</th>
                <th className="py-2 px-3">Nullable</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {table.columns.map((c) => (
                <tr key={c.name} className="hover:bg-slate-50">
                  <td className="py-2 px-3 font-mono font-medium text-slate-900">{c.name}</td>
                  <td className="py-2 px-3">
                    <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs font-mono">
                      {c.canonical_type}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-slate-500 font-mono text-xs">{c.db_type}</td>
                  <td className="py-2 px-3">
                    {c.primary_key && (
                      <span className="px-2 py-0.5 bg-amber-50 text-amber-700 rounded text-xs font-bold">
                        PK
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-3 text-slate-500 text-xs">
                    {c.nullable ? 'YES' : 'NO'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {table.foreign_keys.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">Relationships (Foreign Keys)</h4>
          <div className="space-y-2">
            {table.foreign_keys.map((fk, idx) => (
              <div key={idx} className="p-3 bg-slate-50 rounded border border-slate-200 text-xs font-mono flex items-center justify-between">
                <div>
                  <span className="font-semibold text-slate-800">{table.name}</span>
                  <span className="text-slate-500">({fk.source_columns.join(', ')})</span>
                  <span className="mx-2 text-indigo-600 font-bold">&rarr;</span>
                  <span className="font-semibold text-slate-800">{fk.target_table}</span>
                  <span className="text-slate-500">({fk.target_columns.join(', ')})</span>
                </div>
                <span className="px-2 py-0.5 bg-slate-200 text-slate-700 rounded">
                  {fk.cardinality}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default TableDetails;
