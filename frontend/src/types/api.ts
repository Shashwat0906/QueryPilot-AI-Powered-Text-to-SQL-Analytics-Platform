// Types mirroring the backend's Pydantic models (backend/app/schemas/api.py).

export type QueryStatus = 'success' | 'failed' | 'rejected' | 'unanswerable'
export type CostStatus = 'estimated' | 'unavailable' | 'no_llm_calls'
export type CellValue = string | number | boolean | null

export interface ColumnMeta {
  name: string
  type: 'number' | 'date' | 'string' | 'boolean' | 'null'
}

export interface Attempt {
  number: number
  kind: 'generation' | 'correction'
  sql: string | null
  status: string
  error_code: string | null
  error_message: string | null
  error_category: string | null
  llm_latency_ms: number | null
  db_latency_ms: number | null
}

export interface QueryResponse {
  request_id: string
  created_at: string
  question: string
  status: QueryStatus
  answer: string | null
  sql: string | null
  explanation: string | null
  tables_used: string[]
  assumptions: string[]
  columns: ColumnMeta[]
  rows: CellValue[][]
  row_count: number
  truncated: boolean
  max_rows: number
  attempts: Attempt[]
  retry_count: number
  timings: { generation_ms: number; db_ms: number; answer_ms: number; total_ms: number }
  usage: {
    llm_calls: number
    input_tokens: number | null
    output_tokens: number | null
    estimated_cost_usd: number | null
    cost_status: CostStatus
    cost_note: string
  }
  cache: { hit: boolean; stored: boolean; reason: string | null }
  provider: string
  model: string
  is_mock_provider: boolean
  warnings: string[]
  error: { code: string; message: string; category: string } | null
}

export interface ColumnSchema {
  name: string
  type: string
  nullable: boolean
  primary_key: boolean
  note: string | null
  sample_values: string[] | null
}

export interface TableSchema {
  name: string
  columns: ColumnSchema[]
  primary_key: string[]
  foreign_keys: { column: string; references_table: string; references_column: string }[]
  row_count: number
  note: string | null
}

export interface Relationship {
  from_table: string
  from_column: string
  to_table: string
  to_column: string
}

export interface SchemaResponse {
  version: string
  database_type: string
  data_reference_date: string | null
  business_rules: string[]
  tables: TableSchema[]
  relationships: Relationship[]
}

export interface HistoryItem {
  request_id: string
  created_at: string
  question: string
  status: QueryStatus
  final_sql: string | null
  row_count: number | null
  retry_count: number
  total_ms: number
  cache_hit: boolean
  estimated_cost_usd: number | null
  cost_status: CostStatus
  error_code: string | null
}

export interface HistoryDetail extends HistoryItem {
  error_message: string | null
  error_category: string | null
  explanation: string | null
  answer: string | null
  attempts: Attempt[]
  tables_used: string[]
  assumptions: string[]
  llm_calls: number
  provider: string
  model: string
  input_tokens: number | null
  output_tokens: number | null
  generation_ms: number
  db_ms: number
}

export interface HistoryResponse {
  items: HistoryItem[]
  total: number
  limit: number
  offset: number
}

export interface CacheStats {
  enabled: boolean
  entries: number
  max_entries: number
  ttl_seconds: number
  hits: number
  misses: number
  hit_rate: number | null
  skipped_sensitive: number
}

export interface RecentRequest {
  request_id: string
  created_at: string
  total_ms: number
  generation_ms: number
  db_ms: number
  status: QueryStatus
  cache_hit: boolean
  retry_count: number
  estimated_cost_usd: number | null
  input_tokens: number | null
  output_tokens: number | null
}

export interface AnalyticsResponse {
  total_requests: number
  successful_requests: number
  failed_requests: number
  rejected_requests: number
  unanswerable_requests: number
  success_rate: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  avg_generation_ms: number | null
  avg_db_ms: number | null
  total_estimated_cost_usd: number | null
  avg_estimated_cost_per_request_usd: number | null
  priced_requests: number
  unpriced_requests: number
  retry_rate: number | null
  retry_success_rate: number | null
  total_retries: number
  cache_hits: number
  cache_hit_rate: number | null
  total_input_tokens: number | null
  total_output_tokens: number | null
  token_usage_available_requests: number
  llm_calls: number
  requests_by_day: { date: string; success: number; failed: number; cost_usd: number }[]
  failure_categories: { category: string; count: number }[]
  recent_requests: RecentRequest[]
  cache: CacheStats
}

export interface ConfigResponse {
  app_name: string
  version: string
  environment: string
  database_type: string
  database_name: string
  approved_tables: string[]
  llm_provider: string
  llm_model: string
  is_mock_provider: boolean
  llm_api_key_configured: boolean
  answer_mode: string
  max_result_rows: number
  query_timeout_seconds: number
  max_correction_attempts: number
  max_question_length: number
  rate_limit_per_minute: number
  daily_llm_request_limit: number
  daily_cost_limit_usd: number
  history_scope: 'all' | 'client'
  cache: CacheStats
  model_pricing_usd_per_mtok: { input: number; output: number } | null
  settings_editable: boolean
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  database: 'ok' | 'error'
  database_detail: string | null
  schema_version: string | null
  llm_provider: string
  llm_configured: boolean
  history_storage: 'persistent' | 'temporary'
  uptime_seconds: number
}
