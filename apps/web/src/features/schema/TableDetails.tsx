import React from 'react';
import { CatalogLabelInput } from '../../api/generated/schema.ts';
import { labelFor } from './LabelManager.tsx';

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
  labels?: CatalogLabelInput[];
  disabled?: boolean;
  onLabelChange?: (column: string | null, field: 'display_name' | 'description', value: string) => void;
  table: {
    name: string;
    namespace: string;
    columns: ColumnMeta[];
    primary_key_columns: string[];
    foreign_keys: ForeignKeyMeta[];
  };
}

export function TableDetails({ table, labels = [], disabled = false, onLabelChange }: TableDetailsProps): React.JSX.Element {
  const label = labelFor(labels, table.namespace, table.name);
  const physical = `${table.namespace}.${table.name}`;
  return (
    <div>
      <div className="p-5 space-y-4">
        <div className="actions">
          <h2 className="section-title font-mono">{table.name}</h2>
          <span className="badge">{table.namespace}</span>
        </div>
        {onLabelChange ? <div className="grid gap-4 sm:grid-cols-2">
          <label>Table display name
            <input aria-label={`${physical} display name`} maxLength={200} value={label?.display_name ?? ''}
              onChange={(event) => onLabelChange(null, 'display_name', event.target.value)} disabled={disabled}
              placeholder={table.name} className="block w-full mt-1" />
          </label>
          <label>Description
            <input aria-label={`${physical} description`} maxLength={2000} value={label?.description ?? ''}
              onChange={(event) => onLabelChange(null, 'description', event.target.value)} disabled={disabled}
              placeholder="Describe this table" className="block w-full mt-1" />
          </label>
        </div> : label && <div><p>{label.display_name}</p><p className="text-muted">{label.description}</p></div>}
      </div>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={`${physical} columns`}>
        <table className="schema-table">
          <thead><tr>
            <th scope="col">Column</th><th scope="col">Type</th><th scope="col">Key</th><th scope="col">Nullable</th>
            <th scope="col">Business name</th><th scope="col">Description</th>
          </tr></thead>
          <tbody>
            {table.columns.map((column) => {
              const columnLabel = labelFor(labels, table.namespace, table.name, column.name);
              return <tr key={column.name}>
                <td><span className="font-mono text-xs">{column.name}</span><p className="native-type">{column.db_type}</p></td>
                <td><span className="badge type-tag">{column.canonical_type}</span></td>
                <td>{column.primary_key && <span className="badge badge-pk">PK</span>}</td>
                <td className="text-muted text-xs">{column.nullable ? 'Yes' : 'No'}</td>
                <td>{onLabelChange ? <input aria-label={`${physical}.${column.name} display name`} maxLength={200}
                  placeholder={column.name} value={columnLabel?.display_name ?? ''} disabled={disabled}
                  onChange={(event) => onLabelChange(column.name, 'display_name', event.target.value)} /> : columnLabel?.display_name}</td>
                <td>{onLabelChange ? <input aria-label={`${physical}.${column.name} description`} maxLength={2000}
                  placeholder="Add description" value={columnLabel?.description ?? ''} disabled={disabled}
                  onChange={(event) => onLabelChange(column.name, 'description', event.target.value)} /> : columnLabel?.description}</td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
      {table.foreign_keys.length > 0 && <div className="p-5 border-t border-border space-y-2">
        <h3 className="section-title">Relationships (foreign keys)</h3>
        {table.foreign_keys.map((fk, index) => <div key={index} className="flex flex-wrap justify-between gap-2 text-xs font-mono text-muted">
          <span>{table.name}({fk.source_columns.join(', ')}) → {fk.target_table}({fk.target_columns.join(', ')})</span>
          <span className="badge">{fk.cardinality}</span>
        </div>)}
      </div>}
    </div>
  );
}

export default TableDetails;
