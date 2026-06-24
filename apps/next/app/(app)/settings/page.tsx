import { Icon } from '@/components/app/icon'
import './settings.css'

export default function SettingsPage() {
  return (
    <div className="settings-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-sub">Account preferences, generation defaults and appearance.</p>
        </div>
      </div>

      <div className="set-grid">
        <div className="set-nav">
          <a className="active">Profile</a>
          <a>Generation defaults</a>
          <a>Appearance</a>
          <a>Notifications</a>
          <a>Billing</a>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div className="card">
            <div className="card-head"><div><div className="card-title">Profile</div></div></div>
            <div className="card-body" style={{ paddingTop: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 6 }}>
                <span className="avatar" style={{ width: 52, height: 52, fontSize: 17 }}>KB</span>
                <div>
                  <button className="btn btn-outline btn-sm">Change photo</button>
                  <div className="hint" style={{ marginTop: 6 }}>PNG or JPG, max 1 MB.</div>
                </div>
              </div>
              <div className="row"><div><div className="label">Name</div></div><input className="input" style={{ width: 280 }} defaultValue="Kévin De Benedetti" /></div>
              <div className="row"><div><div className="label">Email</div></div><input className="input" style={{ width: 280 }} defaultValue="kevin@datasetgen.io" /></div>
              <div className="row"><div><div className="label">Interface language</div></div><select className="select" style={{ width: 280 }} defaultValue="English"><option>French</option><option>English</option></select></div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div><div className="card-title">Generation defaults</div><div className="card-desc">Applied to new datasets.</div></div></div>
            <div className="card-body" style={{ paddingTop: 0 }}>
              <div className="row"><div><div className="label">LLM model</div><div className="hint">Model used by default.</div></div><select className="select" style={{ width: 240 }} defaultValue="gpt-4o-mini"><option>gpt-4o-mini</option><option>gpt-4o</option><option>claude-3.5-sonnet</option></select></div>
              <div className="row"><div><div className="label">Target language</div></div><select className="select" style={{ width: 240 }} defaultValue="French (fr)"><option>French (fr)</option><option>English (en)</option><option>Spanish (es)</option><option>German (de)</option></select></div>
              <div className="row"><div><div className="label">Duplicate detection</div><div className="hint">Enabled on creation.</div></div><span className="switch on" /></div>
              <div className="row"><div><div className="label">Automatic Langfuse export</div></div><span className="switch" /></div>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><div><div className="card-title">Appearance</div></div></div>
            <div className="card-body" style={{ paddingTop: 4 }}>
              <div className="label" style={{ marginBottom: 10 }}>Theme</div>
              <div style={{ display: 'flex', gap: 12 }}>
                <div className="theme-opt"><div className="theme-prev" style={{ border: '1px solid var(--border)' }}><div style={{ width: 34, background: '#fafafa' }} /><div style={{ flex: 1, background: '#fff', borderLeft: '1px solid #eee' }} /></div><div className="tl">Light</div></div>
                <div className="theme-opt"><div className="theme-prev"><div style={{ width: 34, background: '#1c1c1c' }} /><div style={{ flex: 1, background: '#262626' }} /></div><div className="tl">Dark</div></div>
                <div className="theme-opt"><div className="theme-prev"><div style={{ width: 48, background: '#fafafa' }} /><div style={{ flex: 1, background: '#262626' }} /></div><div className="tl">System</div></div>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
            <button className="btn btn-ghost">Cancel</button>
            <button className="btn btn-primary"><Icon name="check" />Save</button>
          </div>
        </div>
      </div>
    </div>
  )
}
