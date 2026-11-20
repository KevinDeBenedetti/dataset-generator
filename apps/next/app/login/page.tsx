'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { LanguageSwitch } from '@/components/app/language-switch'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { postLoginRedirect, useAuthProviders, useLogin } from '@/hooks/use-auth'
import { API_BASE_URL, ssoUrl } from '@/api/sdk'

// The API's `?error=` codes (see apps/server/services/identities.py), each
// with its message under `login.errors`.
const SSO_ERRORS = [
  'signup_closed',
  'domain_not_allowed',
  'no_verified_email',
  'link_required',
  'identity_in_use',
  'account_disabled',
  'session_expired',
  'sso_failed',
  'no_subject',
] as const
type SsoError = (typeof SSO_ERRORS)[number]

function ssoError(): SsoError | null {
  if (typeof window === 'undefined') return null
  const code = new URLSearchParams(window.location.search).get('error')
  if (!code) return null
  return SSO_ERRORS.find((known) => known === code) ?? 'sso_failed'
}

export default function LoginPage() {
  const t = useTranslations('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error] = useState(ssoError)
  const loginMutation = useLogin()
  const {
    data: options,
    isPending,
    isError,
    error: optionsError,
    isFetching,
    refetch,
  } = useAuthProviders()
  const providers = (options?.providers ?? []).filter((p) => p.configured)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    loginMutation.mutate({ email, password })
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-4">
      <div className="flex w-full max-w-sm items-center justify-between">
        <Button asChild variant="ghost" size="sm" className="-ml-2.5 text-muted-foreground">
          <Link href="/">
            <ArrowLeft className="size-4" />
            {t('back')}
          </Link>
        </Button>
        <LanguageSwitch className="h-8" />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{t('title')}</CardTitle>
          <CardDescription>
            {options?.signup_open ? t('descriptionSignup') : t('description')}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {error && (
            <p className="text-sm text-red-600" role="alert">
              {t(`errors.${error}`)}
            </p>
          )}

          {/* The sign-in methods come from the API: say so while they load (retries
              included) and when it can't be reached, instead of an empty card. */}
          {isPending && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              {t('loadingOptions')}
            </p>
          )}
          {isError && (
            <div className="flex flex-col gap-2" role="alert">
              <p className="text-sm text-red-600">
                {t('optionsFailed', {
                  url: API_BASE_URL,
                  reason: optionsError instanceof Error ? ` (${optionsError.message})` : '',
                })}
              </p>
              <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>
                {isFetching && <Loader2 className="size-4 animate-spin" />}
                {t('retry')}
              </Button>
            </div>
          )}

          {providers.map((provider) => (
            <Button
              key={provider.name}
              variant="outline"
              className="w-full"
              onClick={() => {
                window.location.href = ssoUrl(provider.name, 'login', postLoginRedirect())
              }}
            >
              {t('continueWith', { provider: provider.label })}
            </Button>
          ))}
          {options && providers.length === 0 && !options.local_login && (
            <p className="text-sm text-muted-foreground">{t('noMethod')}</p>
          )}

          {options?.local_login && (
            <>
              {providers.length > 0 && (
                <div className="my-2 flex items-center gap-2">
                  <Separator className="flex-1" />
                  <span className="text-xs text-muted-foreground">{t('or')}</span>
                  <Separator className="flex-1" />
                </div>
              )}
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <label htmlFor="email" className="text-sm font-medium">
                    {t('email')}
                  </label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={loginMutation.isPending}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label htmlFor="password" className="text-sm font-medium">
                    {t('password')}
                  </label>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={loginMutation.isPending}
                  />
                </div>

                {loginMutation.isError && (
                  <p className="text-sm text-red-600" role="alert">
                    {loginMutation.error instanceof Error
                      ? loginMutation.error.message
                      : t('failed')}
                  </p>
                )}

                <Button type="submit" disabled={loginMutation.isPending}>
                  {loginMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                  {t('submit')}
                </Button>
              </form>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
