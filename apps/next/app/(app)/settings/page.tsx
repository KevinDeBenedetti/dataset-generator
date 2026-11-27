'use client'

import Link from 'next/link'
import { useTranslations } from 'next-intl'
import { Icon } from '@/components/app/icon'
import { Integrations } from '@/components/settings/integrations'
import { LinkedAccounts } from '@/components/settings/linked-accounts'
import { YourData } from '@/components/settings/your-data'
import { useCurrentUser } from '@/hooks/use-auth'
import { rich } from '@/lib/rich'
import { initialsFor } from '@/lib/utils'
import './settings.css'

export default function SettingsPage() {
  const t = useTranslations('settings')
  const tc = useTranslations('common')
  const { data: user } = useCurrentUser()

  return (
    <div className="settings-page">
      <div className="page-head">
        <div>
          <h1 className="page-title">{t('title')}</h1>
          <p className="page-sub">{t('subtitle')}</p>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 720 }}>
        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{t('profile.title')}</div>
            </div>
          </div>
          <div className="card-body" style={{ paddingTop: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 6 }}>
              <span className="avatar" style={{ width: 52, height: 52, fontSize: 17 }}>
                {initialsFor(user?.name)}
              </span>
              <div>
                <div style={{ fontWeight: 500 }}>{user?.name ?? tc('loading')}</div>
                <div className="hint" style={{ marginTop: 4 }}>
                  {user
                    ? t(user.role === 'admin' ? 'profile.admin' : 'profile.user', {
                        provider: user.provider,
                      })
                    : ''}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* The admin of the deployment's secrets acts with the server's keys:
            nothing to link or save here. */}
        {user?.provider === 'secrets' ? (
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">{t('keys.title')}</div>
                <div className="card-desc">{t('keys.managedByDeployment')}</div>
              </div>
            </div>
          </div>
        ) : (
          <>
            <LinkedAccounts />

            <div className="card">
              <div className="card-head">
                <div>
                  <div className="card-title">{t('keys.title')}</div>
                  <div className="card-desc">
                    {t.rich('keys.description', { strong: rich.strong })}
                  </div>
                </div>
              </div>
            </div>

            <Integrations />
          </>
        )}

        <div className="card">
          <div className="card-head">
            <div>
              <div className="card-title">{t('models.title')}</div>
              <div className="card-desc">{t('models.description')}</div>
            </div>
          </div>
          <div className="card-foot">
            <Link className="btn btn-outline" href="/models">
              <Icon name="cpu" />
              {t('models.open')}
            </Link>
          </div>
        </div>
        <YourData />
      </div>
    </div>
  )
}
