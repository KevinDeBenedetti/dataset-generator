'use client'

import { useEffect } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import {
  useAuthProviders,
  useIdentities,
  useLogoutEverywhere,
  useUnlinkIdentity,
} from '@/hooks/use-auth'
import { ssoUrl } from '@/api/sdk'

// The `?error=` codes that have a message under `settings.accounts.errors`.
const LINK_ERRORS = ['identity_in_use', 'sso_failed', 'session_expired'] as const
type LinkError = (typeof LINK_ERRORS)[number]

function linkError(code: string): LinkError {
  return LINK_ERRORS.find((known) => known === code) ?? 'sso_failed'
}

export function LinkedAccounts() {
  const t = useTranslations('settings')
  const locale = useLocale()
  const { data } = useIdentities()
  const { data: options } = useAuthProviders()
  const unlink = useUnlinkIdentity()
  const everywhere = useLogoutEverywhere()

  // Coming back from a provider: ?linked=github or ?error=identity_in_use.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const linked = params.get('linked')
    const error = params.get('error')
    if (linked) toast.success(t('accounts.linked', { provider: linked }))
    if (error) {
      toast.error(t(`accounts.errors.${linkError(error)}`))
    }
    if (linked || error) window.history.replaceState(null, '', window.location.pathname)
  }, [t])

  const identities = data?.identities ?? []
  const ways = identities.length + (data?.has_password && options?.local_login ? 1 : 0)
  const linkable = (options?.providers ?? []).filter(
    (p) => p.configured && !identities.some((i) => i.provider === p.name),
  )
  const label = (name: string) => options?.providers.find((p) => p.name === name)?.label ?? name

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{t('accounts.title')}</div>
          <div className="card-desc">
            {t('accounts.description')}
            {data?.locked_admin && ` ${t('accounts.lockedAdmin')}`}
          </div>
        </div>
      </div>
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {identities.map((identity) => (
          <div
            key={identity.id}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
          >
            <div>
              <div style={{ fontWeight: 500 }}>{label(identity.provider)}</div>
              <div className="hint">
                {identity.username ?? identity.email ?? ''}
                {identity.last_login_at &&
                  ` · ${t('accounts.lastUsed', {
                    date: new Date(identity.last_login_at).toLocaleDateString(locale),
                  })}`}
              </div>
            </div>
            <button
              className="btn btn-outline btn-sm"
              type="button"
              disabled={ways <= 1 || unlink.isPending}
              title={ways <= 1 ? t('accounts.onlyWay') : undefined}
              onClick={() =>
                unlink.mutate(identity.id, {
                  onSuccess: () =>
                    toast.success(t('accounts.unlinked', { provider: label(identity.provider) })),
                  onError: (e: Error) => toast.error(e.message),
                })
              }
            >
              {t('accounts.unlink')}
            </button>
          </div>
        ))}
        {data?.has_password && options?.local_login && (
          <div className="hint">{t('accounts.passwordEnabled')}</div>
        )}
        {linkable.length > 0 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {linkable.map((p) => (
              <a key={p.name} className="btn btn-outline" href={ssoUrl(p.name, 'link')}>
                <Icon name="plus" />
                {t('accounts.link', { provider: p.label })}
              </a>
            ))}
          </div>
        )}
      </div>
      <div className="card-foot">
        <button
          className="btn btn-outline"
          type="button"
          disabled={everywhere.isPending}
          onClick={() => everywhere.mutate()}
        >
          {t('accounts.signOutEverywhere')}
        </button>
      </div>
    </div>
  )
}
