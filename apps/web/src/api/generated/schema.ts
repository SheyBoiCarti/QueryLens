/**
 * Explicit TypeScript contracts corresponding to OpenAPI schema.
 * scripts/export_schema.py exports JSON; keep these declarations in sync.
 */

export interface UserResponse {
  id: string;
  email: string;
  role: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  user: UserResponse;
  csrf_token: string;
}

export interface CsrfResponse {
  csrf_token: string;
}

export interface StatusResponse {
  status: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
  request_id: string;
}

export interface ErrorEnvelope {
  error: ErrorDetail;
}

// Connection interfaces for Phase 02
export interface ConnectionCreate {
  name: string;
  engine: 'postgresql' | 'mysql';
  host: string;
  port: number;
  database: string;
  username: string;
  password?: string;
  tls_enabled?: boolean;
  ca_cert?: string;
  allowed_tables?: Record<string, string[]>;
}

export interface ConnectionResponse {
  id: string;
  user_id: string;
  name: string;
  engine: 'postgresql' | 'mysql';
  host: string;
  port: number;
  database: string;
  username: string;
  tls_enabled: boolean;
  allowed_tables?: Record<string, string[]>;
  created_at: string;
  updated_at: string;
}

// Query interfaces for Phase 05 / 08
export type QueryRunStatus =
  | 'queued'
  | 'contextualizing'
  | 'generating'
  | 'validating'
  | 'executing'
  | 'repairing'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'rejected'
  | 'clarification_required'
  | 'cancelled'
  | 'interrupted';

export interface ColumnMeta {
  name: string;
  type: 'integer' | 'decimal' | 'float' | 'string' | 'boolean' | 'date' | 'datetime';
  db_type: string;
}

export interface PublicRunBase {
  query_id: string;
  connection_id: string;
  status: QueryRunStatus;
  state_version: number;
  question: string;
  created_at: string;
  updated_at: string;
  origin?: RunOrigin;
  parent_query_id?: string | null;
  source_query_id?: string | null;
  saved_question_id?: string | null;
  saved_question_version?: number | null;
}

export interface PublicRunCompleted extends PublicRunBase {
  status: 'completed';
  dialect: 'postgresql' | 'mysql';
  sql: string;
  assumptions: string[];
  warnings: string[];
  columns: ColumnMeta[];
  row_count: number;
  truncated: boolean;
  results_available: boolean;
  results_expires_at?: string;
  rows?: Record<string, string | number | boolean | null>[];
  context?: RunContext | null;
  presentation?: PresentationMetadata | null;
}

export interface PublicRunClarification extends PublicRunBase {
  status: 'clarification_required';
  clarification_question: string;
}

export interface PublicRunFailed extends PublicRunBase {
  status: 'failed' | 'rejected' | 'interrupted';
  error_code: string;
  safe_message: string;
}

export interface PublicRunCancelled extends PublicRunBase {
  status: 'cancelled';
  safe_message: string;
}

export interface PublicRunPending extends PublicRunBase {
  status: 'queued' | 'contextualizing' | 'generating' | 'validating' | 'executing' | 'repairing' | 'cancelling';
}

export type PublicRun =
  | PublicRunCompleted
  | PublicRunClarification
  | PublicRunFailed
  | PublicRunCancelled
  | PublicRunPending;

// Everyday Analytics semantic metadata (OpenAPI Task 2).
export type MetricAggregation = 'sum' | 'count' | 'count_distinct' | 'avg' | 'min' | 'max';
export type FilterOperator = 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'not_in' | 'is_null' | 'is_not_null';

export interface MetricFilter {
  column: string;
  operator: FilterOperator;
  value?: unknown;
}

export interface MetricDSL {
  key: string;
  name: string;
  description?: string | null;
  table: string;
  measure_column: string;
  aggregation: MetricAggregation;
  filters?: MetricFilter[];
  grain?: string[];
  units?: string | null;
  synonyms?: string[];
}

export interface MetricResponse {
  id: string;
  connection_id: string;
  key: string;
  name: string;
  description: string | null;
  dsl: MetricDSL;
  version: number;
  enabled: boolean;
}

export interface UpdateMetricRequest {
  expected_version: number;
  dsl?: MetricDSL;
  enabled?: boolean;
}

export interface CatalogLabelInput {
  namespace: string;
  table_name: string;
  column_name?: string | null;
  display_name: string;
  description?: string | null;
}

export interface LabelReference extends CatalogLabelInput {
  version: number;
}

export interface LabelsResponse {
  semantic_version: number;
  labels: LabelReference[];
}

export interface ReplaceLabelsRequest {
  expected_semantic_version: number;
  labels: CatalogLabelInput[];
}

export type RunOrigin = 'natural_language' | 'follow_up' | 'manual_sql' | 'saved_question';

export interface ObjectReference {
  namespace: string;
  table_name: string;
  column_name?: string | null;
  canonical_type?: ColumnMeta['type'] | null;
  db_type?: string | null;
}

export interface MetricReference {
  id: string;
  key: string;
  version: number;
  dsl_hash: string;
}

export interface AppliedFilter {
  slot_id: string;
  column: ObjectReference;
  operator: '=' | '!=' | '<>' | '<' | '<=' | '>' | '>=' | 'IN' | 'BETWEEN' | 'date_range';
  value: string | number | boolean | (string | number | boolean)[];
}

export interface RunContext {
  effective_question: string;
  canonical_sql_template: string;
  author_limit?: number | null;
  applied_filters?: AppliedFilter[];
  metric_references?: MetricReference[];
  label_references?: LabelReference[];
  referenced_objects?: ObjectReference[];
  snapshot_hash: string;
  policy_version: number;
  semantic_version: number;
}

export interface VerifiedDefinition {
  id: string;
  key: string;
  version: number;
  name: string;
  description?: string | null;
  units?: string | null;
}

export interface PresentationMetadata {
  title: string;
  explanation: string;
  chart_type?: 'table' | 'single_value' | 'line' | 'bar';
  x_column?: string | null;
  y_column?: string | null;
  value?: string | null;
  plot_row_order?: number[];
  date_scope?: AppliedFilter[];
  verified_definitions?: VerifiedDefinition[];
  units?: string | null;
  warnings?: string[];
}

export interface CreateSQLQueryRequest {
  connection_id: string;
  sql: string;
  source_query_id?: string | null;
  max_rows?: number;
}

export interface CreateQueryResponse {
  query_id: string;
  status: string;
}

export interface HistoryItem {
  id: string;
  connection_id: string;
  question: string;
  status: string;
  created_at: string;
  max_rows: number;
  results_available: boolean;
  origin?: RunOrigin;
  parent_query_id?: string | null;
  source_query_id?: string | null;
  saved_question_id?: string | null;
  saved_question_version?: number | null;
}

export interface HistoryResponse {
  items: HistoryItem[];
  next_cursor?: string | null;
}
