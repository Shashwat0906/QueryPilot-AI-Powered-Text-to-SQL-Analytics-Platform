import { Eraser } from 'lucide-react'
import { useState } from 'react'
import { Button } from '../components/Button'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { ErrorNotice, Loading } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { api } from '../services/api'
import { formatPercent } from '../utils/format'

export function SettingsPage() {
  const config = useAsync(() => api.config(), [])
  const health = useAsync(() => api.health(), [])
  const [cleared, setCleared] = useState<string | null>(null)
  const [clearing, setClearing] = useState(false)

  async function clearCache() {
    setClearing(true)
    try {
      const r = await api.clearCache()
      setCleared(`Cleared ${r.cleared_entries} cached ${r.cleared_entries === 1 ? 'result' : 'results'}.`)
      config.reload()
    } catch (e) {
      setCleared(e instanceof Error ? e.message : 'Could not clear the cache.')
    } finally {
      setClearing(false)
    }
  }

  const c = config.data
  const h = health.data

  return (
    <>
      <PageHeader
        title="Settings"
        description="Current configuration, read from the backend. Values are set with environment variables in backend/.env and need a restart to change."
      />
      {config.error ? (
        <ErrorNotice error={config.error} onRetry={config.reload} />
      ) : !c ? (
        <Loading />
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Health">
            {health.error ? (
              <p className="text-bad">The backend didn’t respond to the health check.</p>
            ) : !h ? (
              <Loading />
            ) : (
              <List
                rows={[
                  ['Overall', h.status === 'ok' ? 'Healthy' : 'Degraded', h.status === 'ok' ? 'text-ok' : 'text-bad'],
                  ['Database', h.database === 'ok' ? 'Reachable' : h.database_detail ?? 'Unreachable', h.database === 'ok' ? 'text-ok' : 'text-bad'],
                  [
                    'History storage',
                    h.history_storage === 'persistent' ? 'Persistent' : 'Temporary (history database unreachable)',
                    h.history_storage === 'persistent' ? 'text-ok' : 'text-warn',
                  ],
                  ['Backend version', h.version],
                  ['Uptime', `${Math.round(h.uptime_seconds / 60)} min`],
                ]}
              />
            )}
          </Panel>

          <Panel title="Language model">
            <List
              rows={[
                ['Provider', c.is_mock_provider ? 'Offline mock (not an LLM)' : c.llm_provider === 'anthropic' ? 'Anthropic Claude' : 'OpenAI-compatible'],
                ['Model', c.llm_model],
                ['API key', c.llm_api_key_configured ? 'Configured (hidden)' : 'Not configured', c.llm_api_key_configured ? 'text-ok' : 'text-warn'],
                ['Answer writing', c.answer_mode === 'llm' ? 'LLM summary of returned rows' : 'Template from returned rows'],
                [
                  'Price used for estimates',
                  c.model_pricing_usd_per_mtok
                    ? `$${c.model_pricing_usd_per_mtok.input} in / $${c.model_pricing_usd_per_mtok.output} out per million tokens`
                    : 'None (cost shown as unavailable)',
                ],
              ]}
            />
          </Panel>

          <Panel title="Database and safety limits">
            <List
              rows={[
                ['Database', `${c.database_type} (${c.database_name})`],
                ['Approved tables', c.approved_tables.join(', ')],
                ['Access', 'Read-only connection'],
                ['Maximum rows per result', c.max_result_rows.toLocaleString()],
                ['Query timeout', `${c.query_timeout_seconds} s`],
                ['Correction attempts', `Up to ${c.max_correction_attempts} after the first try`],
                ['Question length limit', `${c.max_question_length} characters`],
                ['Rate limit', `${c.rate_limit_per_minute} questions per minute per client`],
                [
                  'Daily limit (all visitors)',
                  c.daily_llm_request_limit > 0 || c.daily_cost_limit_usd > 0
                    ? [
                        c.daily_llm_request_limit > 0 ? `${c.daily_llm_request_limit} new questions` : null,
                        c.daily_cost_limit_usd > 0 ? `$${c.daily_cost_limit_usd.toFixed(2)} estimated LLM cost` : null,
                      ]
                        .filter(Boolean)
                        .join(', or ')
                    : 'None',
                ],
                ['History visibility', c.history_scope === 'client' ? 'Each browser sees only its own questions' : 'Shared'],
              ]}
            />
          </Panel>

          <Panel
            title="Result cache"
            description="In-memory, per backend process. Lost on restart."
            actions={
              <Button size="sm" icon={<Eraser size={14} />} onClick={clearCache} disabled={clearing || !c.cache.enabled}>
                Clear cache
              </Button>
            }
          >
            <List
              rows={[
                ['Status', c.cache.enabled ? 'Enabled' : 'Disabled (CACHE_ENABLED=false)', c.cache.enabled ? 'text-ok' : 'text-warn'],
                ['Entries', `${c.cache.entries} of ${c.cache.max_entries}`],
                ['Lifetime', `${c.cache.ttl_seconds / 60} minutes`],
                ['Hits / misses', `${c.cache.hits} / ${c.cache.misses}`],
                ['Hit rate (since start)', formatPercent(c.cache.hit_rate)],
                ['Not cached (sensitive columns)', String(c.cache.skipped_sensitive)],
              ]}
            />
            {cleared && (
              <p className="mt-3 text-sm text-teal" role="status">
                {cleared}
              </p>
            )}
          </Panel>
        </div>
      )}
    </>
  )
}

function List({ rows }: { rows: [string, string, string?][] }) {
  return (
    <dl className="divide-y divide-line text-sm">
      {rows.map(([label, value, cls]) => (
        <div key={label} className="flex flex-wrap justify-between gap-x-4 gap-y-0.5 py-2 first:pt-0 last:pb-0">
          <dt className="text-muted">{label}</dt>
          <dd className={`text-right ${cls ?? 'text-ink'}`}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
