// Thin client for the QueryPilot REST API. The browser only ever talks to the
// backend - it never sends SQL to the database itself.
import type {
  AnalyticsResponse,
  ConfigResponse,
  HealthResponse,
  HistoryDetail,
  HistoryResponse,
  QueryResponse,
  SchemaResponse,
} from '../types/api'

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

// Anonymous, random ID for this browser. On a public deployment the backend
// uses it to show each visitor only their own history. It is not a login:
// anyone who has the ID can see that history. Falls back to a per-tab ID when
// storage is unavailable (private mode, blocked cookies).
const CLIENT_ID_KEY = 'querypilot.clientId'
let memoryClientId: string | null = null

function clientId(): string {
  try {
    let id = localStorage.getItem(CLIENT_ID_KEY)
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem(CLIENT_ID_KEY, id)
    }
    return id
  } catch {
    memoryClientId ??= crypto.randomUUID()
    return memoryClientId
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message)
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        'X-Client-ID': clientId(),
        ...init?.headers,
      },
    })
  } catch {
    const hint = import.meta.env.DEV
      ? ' Is the backend running on port 8000?'
      : ' The server may be starting up - try again in a minute.'
    throw new ApiError(0, 'network_error', `Cannot reach the QueryPilot API.${hint}`, null)
  }
  const text = await response.text()
  const body = text ? safeJson(text) : null
  if (!response.ok) {
    const err = (body as { error?: { code?: string; message?: string; request_id?: string; details?: { fields?: { field: string; message: string }[] } } } | null)?.error
    const fieldMessage = err?.details?.fields?.map((f) => `${f.field}: ${f.message}`).join('; ')
    throw new ApiError(
      response.status,
      err?.code ?? 'http_error',
      fieldMessage || err?.message || `Request failed with HTTP ${response.status}.`,
      err?.request_id ?? response.headers.get('X-Request-ID'),
    )
  }
  return body as T
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  schema: () => request<SchemaResponse>('/api/schema'),
  config: () => request<ConfigResponse>('/api/config'),
  analytics: () => request<AnalyticsResponse>('/api/analytics'),
  query: (question: string, useCache = true) =>
    request<QueryResponse>('/api/query', {
      method: 'POST',
      body: JSON.stringify({ question, use_cache: useCache }),
    }),
  history: (params: { limit?: number; offset?: number; status?: string; search?: string } = {}) => {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') search.set(k, String(v))
    })
    return request<HistoryResponse>(`/api/history?${search}`)
  },
  historyDetail: (id: string) => request<HistoryDetail>(`/api/history/${encodeURIComponent(id)}`),
  clearCache: () => request<{ cleared_entries: number }>('/api/cache/clear', { method: 'POST' }),
}
