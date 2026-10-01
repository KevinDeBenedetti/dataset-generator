'use client'

import { useEffect } from 'react'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import {
  useAuthProviders,
  useIdentities,
  useLogoutEverywhere,
  useUnlinkIdentity,
} from '@/hooks/use-auth'
import { ssoUrl } from '@/api/sdk'

const LINK_ERRORS: Record<string, string> = {
  identity_in_use: 'That account is already linked to another DatasetGen account.',
  sso_failed: 'Linking did not complete. Please try again.',
  session_expired: 'Your session expired. Sign in again, then retry.',
}

export function LinkedAccounts() {
  const { data } = useIdentities()
  const { data: options } = useAuthProviders()
  const unlink = useUnlinkIdentity()
  const everywhere = useLogoutEverywhere()

  // Coming back from a provider: ?linked=github or ?error=identity_in_use.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const linked = params.get('linked')
    const error = params.get('error')
    if (linked) toast.success(`${linked} linked`)
    if (error) toast.error(LINK_ERRORS[error] ?? LINK_ERRORS.sso_failed)
    if (linked || error) window.history.replaceState(null, '', window.location.pathname)
  }, [])

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
          <div className="card-title">Sign-in methods</div>
          <div className="card-desc">
            Accounts you can sign in with. You always keep at least one.
            {data?.locked_admin && ' Your email is a platform administrator address.'}
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
                  ` · last used ${new Date(identity.last_login_at).toLocaleDateString()}`}
              </div>
            </div>
            <button
              className="btn btn-outline btn-sm"
              type="button"
              disabled={ways <= 1 || unlink.isPending}
              title={ways <= 1 ? 'Your only way to sign in' : undefined}
              onClick={() =>
                unlink.mutate(identity.id, {
                  onSuccess: () => toast.success(`${label(identity.provider)} unlinked`),
                  onError: (e: Error) => toast.error(e.message),
                })
              }
            >
              Unlink
            </button>
          </div>
        ))}
        {data?.has_password && options?.local_login && (
          <div className="hint">Email and password sign-in is enabled for this account.</div>
        )}
        {linkable.length > 0 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {linkable.map((p) => (
              <a key={p.name} className="btn btn-outline" href={ssoUrl(p.name, 'link')}>
                <Icon name="plus" />
                Link {p.label}
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
          Sign out everywhere
        </button>
      </div>
    </div>
  )
}
