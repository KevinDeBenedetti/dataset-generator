'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { LanguageSwitch } from '@/components/app/language-switch'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAdminLogin, useAuthProviders } from '@/hooks/use-auth'

// The admin's sign-in, against the deployment's secrets (ADR 0002). Not linked
// from the public login page.
export default function AdminLoginPage() {
  const t = useTranslations('adminLogin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const loginMutation = useAdminLogin()
  const { data: options } = useAuthProviders()
  const askOtp = Boolean(options?.admin_totp)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    loginMutation.mutate({ username, password, otp: askOtp ? otp : undefined })
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
          <CardDescription>{t('description')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="username" className="text-sm font-medium">
                {t('username')}
              </label>
              <Input
                id="username"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
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
            {askOtp && (
              <div className="flex flex-col gap-1">
                <label htmlFor="otp" className="text-sm font-medium">
                  {t('otp')}
                </label>
                <Input
                  id="otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9 ]{6,7}"
                  required
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  disabled={loginMutation.isPending}
                />
              </div>
            )}

            {loginMutation.isError && (
              <p className="text-sm text-red-600" role="alert">
                {loginMutation.error instanceof Error ? loginMutation.error.message : t('failed')}
              </p>
            )}

            <Button type="submit" disabled={loginMutation.isPending}>
              {loginMutation.isPending && <Loader2 className="size-4 animate-spin" />}
              {t('submit')}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
