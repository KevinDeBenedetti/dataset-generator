import { Icon } from '@/components/app/icon'
import './api-keys.css'

export default function ApiKeysPage() {
  return (
    <div className="apikeys-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">API keys &amp; integrations</h1>
          <p className="page-sub">Connect your LLM providers and Langfuse, and manage access keys for the DatasetGen REST API.</p>
        </div>
      </div>

      <div className="grid-2" style={{ alignItems: 'start', gap: '24px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div className="card">
            <div className="card-head"><div><div className="card-title">Integrations</div><div className="card-desc">Providers connected to the pipeline.</div></div></div>
            <div className="card-body" style={{ paddingTop: '4px' }}>
              <div className="integ"><span className="ii"><Icon name="sparkles" className="ic-lg" /></span><div style={{ flex: 1 }}><h4>OpenAI</h4><p>gpt-4o, gpt-4o-mini · active key</p></div><span className="badge badge-success"><span className="dot" />Connected</span></div>
              <div className="integ"><span className="ii"><Icon name="cpu" className="ic-lg" /></span><div style={{ flex: 1 }}><h4>Anthropic</h4><p>claude-3.5-sonnet · active key</p></div><span className="badge badge-success"><span className="dot" />Connected</span></div>
              <div className="integ"><span className="ii"><Icon name="zap" className="ic-lg" /></span><div style={{ flex: 1 }}><h4>Langfuse</h4><p>Export of training datasets</p></div><span className="badge badge-success"><span className="dot" />Connected</span></div>
              <div className="integ"><span className="ii"><Icon name="bolt" className="ic-lg" /></span><div style={{ flex: 1 }}><h4>Mistral AI</h4><p>mistral-large · not configured</p></div><button className="btn btn-outline btn-sm">Connect</button></div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div><div className="card-title">Webhooks</div><div className="card-desc">Notified when a job finishes.</div></div><button className="btn btn-outline btn-sm"><Icon name="plus" />Add</button></div>
            <div className="card-body" style={{ paddingTop: 0 }}><div className="keyrow"><span className="keyval">https://hooks.acme.io/datasetgen</span><span className="badge badge-success"><span className="dot" />Active</span><button className="icon-btn"><Icon name="more" /></button></div></div>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><div><div className="card-title">REST API keys</div><div className="card-desc">Programmatic access to DatasetGen.</div></div><button className="btn btn-primary btn-sm"><Icon name="plus" />Generate a key</button></div>
          <div className="card-body" style={{ paddingTop: '4px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div>
              <div className="keyrow" style={{ marginBottom: '6px' }}><span style={{ fontWeight: 500, fontSize: '13.5px' }}>production</span><span className="badge badge-secondary" style={{ marginLeft: 'auto' }}>read/write</span></div>
              <div className="keyrow"><span className="keyval">dg_live_••••••••••••••••3f7a</span><button className="btn btn-outline btn-sm"><Icon name="eye" /></button><button className="btn btn-outline btn-sm"><Icon name="copy" /></button></div>
              <div className="hint" style={{ marginTop: '6px' }}>Created Jan 14, 2026 · last used 12 min ago</div>
            </div>
            <hr className="sep" />
            <div>
              <div className="keyrow" style={{ marginBottom: '6px' }}><span style={{ fontWeight: 500, fontSize: '13.5px' }}>ci-readonly</span><span className="badge badge-outline" style={{ marginLeft: 'auto' }}>read only</span></div>
              <div className="keyrow"><span className="keyval">dg_live_••••••••••••••••a91c</span><button className="btn btn-outline btn-sm"><Icon name="eye" /></button><button className="btn btn-outline btn-sm"><Icon name="copy" /></button></div>
              <div className="hint" style={{ marginTop: '6px' }}>Created Feb 2, 2026 · used by GitHub Actions</div>
            </div>
            <hr className="sep" />
            <div style={{ background: 'var(--muted)', borderRadius: '9px', padding: '14px', fontFamily: "'Geist Mono',monospace", fontSize: '12px', lineHeight: 1.6, color: 'var(--muted-foreground)' }}><span style={{ color: 'var(--info)' }}>curl</span> https://api.datasetgen.io/v1/datasets \
  -H <span style={{ color: 'var(--success)' }}>&quot;Authorization: Bearer dg_live_…&quot;</span></div>
          </div>
        </div>
      </div>
    </div>
  )
}
