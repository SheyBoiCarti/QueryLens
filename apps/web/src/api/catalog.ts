/** Catalog contracts mirror the public OpenAPI CatalogSnapshot schema. */
export interface CatalogColumn {
  name: string;
  canonical_type: string;
  db_type: string;
  nullable: boolean;
  primary_key: boolean;
  comment?: string | null;
}

export interface CatalogTable {
  name: string;
  namespace: string;
  columns: CatalogColumn[];
  primary_key_columns: string[];
  foreign_keys: {
    name?: string | null;
    source_columns: string[];
    target_table: string;
    target_columns: string[];
    cardinality: string;
  }[];
}

export interface CatalogSnapshot {
  connection_id: string;
  engine: string;
  snapshot_hash: string;
  policy_version: number;
  tables: CatalogTable[];
}
