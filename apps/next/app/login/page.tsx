'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { useAuthProviders, useLogin } from '@/hooks/use-auth'
import { ssoUrl } from '@/api/sdk'

// What the API's `?error=` codes mean (see apps/server/services/identities.py).
const SSO_ERRORS: Record<string, string> = {
  signup_closed: 'New accounts are not open at the moment.',
  domain_not_allowed: 'Accounts are limited to certain email domains.',
  no_verified_email:
    'Your account at this provider has no verified email address. Verify one there, then try again.',
  link_required:
    'An account with this email already exists. Sign in to it another way, then link this provider from Settings.',
  identity_in_use: 'This sign-in is already linked to another account.',
  account_disabled: 'This account is disabled.',
  session_expired: 'Your session expired. Sign in again.',
  sso_failed: 'Sign-in did not complete. Please try again.',
  no_subject: 'The provider did not identify your account.',
}

function ssoError(): string | null {
  if (typeof window === 'undefined') return null
  const code = new URLSearchParams(window.location.search).get('error')
  return code ? (SSO_ERRORS[code] ?? SSO_ERRORS.sso_failed) : null
}

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error] = useState(ssoError)
  const loginMutation = useLogin()
  const { data: options, isPending } = useAuthProviders()
  const providers = (options?.providers ?? []).filter((p) => p.configured)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    loginMutation.mutate({ email, password })
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            {options?.signup_open
              ? 'Access your datasets — a first sign-in creates your account.'
              : 'Access your datasets'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {error && (
            <p className="text-sm text-red-600" role="alert">
              {error}
            </p>
          )}

          {providers.map((provider) => (
            <Button
              key={provider.name}
              variant="outline"
              className="w-full"
              onClick={() => {
                window.location.href = ssoUrl(provider.name)
              }}
            >
              Continue with {provider.label}
            </Button>
          ))}
          {!isPending && providers.length === 0 && !options?.local_login && (
            <p className="text-sm text-muted-foreground">No sign-in method is configured.</p>
          )}

          {options?.local_login && (
            <>
              {providers.length > 0 && (
                <div className="my-2 flex items-center gap-2">
                  <Separator className="flex-1" />
                  <span className="text-xs text-muted-foreground">OR</span>
                  <Separator className="flex-1" />
                </div>
              )}
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <label htmlFor="email" className="text-sm font-medium">
                    Email
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
                    Password
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
                      : 'Login failed'}
                  </p>
                )}

                <Button type="submit" disabled={loginMutation.isPending}>
                  {loginMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                  Sign in
                </Button>
              </form>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
