'use client'

import Link from 'next/link'
import { Icon } from '@/components/app/icon'
import { Integrations } from '@/components/settings/integrations'
import { LinkedAccounts } from '@/components/settings/linked-accounts'
import { YourData } from '@/components/settings/your-data'
import { useCurrentUser } from '@/hooks/use-auth'
import { initialsFor } from '@/lib/utils'
import './settings.css'

export default function SettingsPage() {
  const { data: user } = useCurrentUser()

  return (
    <div className="settings-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-sub">
            Your account and the keys your requests run on. Generation models are set on the Models
            page.
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 720 }}>
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Profile</div>
            </div>
          </div>
          <div className="card-body" style={{ paddingTop: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 6 }}>
              <span className="avatar" style={{ width: 52, height: 52, fontSize: 17 }}>
                {initialsFor(user?.email)}
              </span>
              <div>
                <div style={{ fontWeight: 500 }}>{user?.email ?? 'Loading…'}</div>
                <div className="hint" style={{ marginTop: 4 }}>
                  {user
                    ? `${user.role === 'admin' ? 'Admin' : 'User'} · ${user.provider} sign-in`
                    : ''}
                </div>
              </div>
            </div>
          </div>
        </div>

        <LinkedAccounts />

        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Your keys</div>
              <div className="card-desc">
                Every model call and Hugging Face upload runs on <strong>your own</strong> keys.
                They are stored encrypted, only ever sent to their provider, and nobody —
                administrators included — can read them back.
              </div>
            </div>
          </div>
        </div>

        <Integrations />

        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">Generation defaults</div>
              <div className="card-desc">
                The default model of each step (cleaning, Q&amp;A, vision, jobs) and the OpenAI /
                Claude subscription providers.
              </div>
            </div>
          </div>
          <div className="card-foot">
            <Link className="btn btn-outline" href="/models">
              <Icon name="cpu" />
              Open Models
            </Link>
          </div>
        </div>
        <YourData />
      </div>
    </div>
  )
}
