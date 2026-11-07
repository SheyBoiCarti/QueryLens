/**
 * Generated TypeScript contracts corresponding to OpenAPI schema.
 * Generated via scripts/export_schema.py.
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
  rows?: Record<string, any>[];
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
