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
import { postLoginRedirect, useAuthProviders, useHfLogin, useLogin } from '@/hooks/use-auth'
import { API_BASE_URL, ssoUrl } from '@/api/sdk'
import { SignInError } from '@/api/errors'

// The Hub's token page, on its "write" preset: the token the app needs.
const WRITE_TOKEN_URL = 'https://huggingface.co/settings/tokens/new?preset=write'

// The API's refusal codes of POST /auth/hf (apps/server/auth/hf_token.py), each
// with its message under `login.hf.errors`.
const HF_ERRORS = [
  'token_malformed',
  'token_invalid',
  'token_other_account',
  'token_read_only',
  'signup_closed',
  'signup_not_member',
  'signup_orgs_hidden',
  'account_disabled',
  'hub_unavailable',
  'rate_limited',
] as const
type HfError = (typeof HF_ERRORS)[number]

function hfError(error: unknown): HfError | null {
  if (!(error instanceof SignInError)) return null
  return HF_ERRORS.find((known) => known === error.code) ?? null
}

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
  const [hfUsername, setHfUsername] = useState('')
  const [hfToken, setHfToken] = useState('')
  const hfMutation = useHfLogin()
  const hfRefusal = hfError(hfMutation.error)
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

  const handleHfSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    hfMutation.mutate({ username: hfUsername.trim(), token: hfToken.trim() })
  }

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

          <form onSubmit={handleHfSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="hf-username" className="text-sm font-medium">
                {t('hf.username')}
              </label>
              <Input
                id="hf-username"
                autoComplete="username"
                required
                value={hfUsername}
                onChange={(e) => setHfUsername(e.target.value)}
                disabled={hfMutation.isPending}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="hf-token" className="text-sm font-medium">
                {t('hf.token')}
              </label>
              <Input
                id="hf-token"
                type="password"
                autoComplete="off"
                spellCheck={false}
                required
                placeholder="hf_…"
                value={hfToken}
                onChange={(e) => setHfToken(e.target.value)}
                disabled={hfMutation.isPending}
              />
              <p className="text-xs text-muted-foreground">
                {t('hf.tokenHelp')}{' '}
                <a
                  href={WRITE_TOKEN_URL}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="underline"
                >
                  {t('hf.createToken')}
                </a>
              </p>
            </div>

            {hfMutation.isError && (
              <p className="text-sm text-red-600" role="alert">
                {hfRefusal
                  ? t(`hf.errors.${hfRefusal}`)
                  : hfMutation.error instanceof Error
                    ? hfMutation.error.message
                    : t('failed')}
                {hfRefusal === 'token_read_only' && (
                  <>
                    {' '}
                    <a
                      href={WRITE_TOKEN_URL}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="underline"
                    >
                      {t('hf.createToken')}
                    </a>
                  </>
                )}
              </p>
            )}

            <Button type="submit" disabled={hfMutation.isPending}>
              {hfMutation.isPending && <Loader2 className="size-4 animate-spin" />}
              {t('hf.submit')}
            </Button>
          </form>

          {(providers.length > 0 || options?.local_login) && (
            <div className="my-2 flex items-center gap-2">
              <Separator className="flex-1" />
              <span className="text-xs text-muted-foreground">{t('or')}</span>
              <Separator className="flex-1" />
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
