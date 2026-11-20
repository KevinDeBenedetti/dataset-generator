'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useLocale, useTranslations } from 'next-intl'
import { LOCALES, localeCookie, type Locale } from '@/i18n/config'
import { cn } from '@/lib/utils'

function remember(locale: Locale) {
  document.cookie = localeCookie(locale, window.location.protocol === 'https:')
}

/** Shows the other language's code and switches to it: the choice goes into a
 *  cookie and the page is rendered again in that language, where it stands.
 *  The API answers in the reader's language too (apps/server/core/i18n.py), so
 *  what it already sent is fetched again. */
export function LanguageSwitch({ className }: { className?: string }) {
  const locale = useLocale()
  const t = useTranslations('language')
  const router = useRouter()
  const queryClient = useQueryClient()
  const other = LOCALES.find((candidate) => candidate !== locale) ?? locale
  const label = t('switchTo', { language: t(other) })

  return (
    <button
      type="button"
      lang={other}
      title={label}
      aria-label={label}
      className={cn(
        'inline-flex min-w-[34px] items-center justify-center rounded-md text-[12px] font-semibold uppercase text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
        className,
      )}
      onClick={() => {
        remember(other)
        router.refresh()
        void queryClient.invalidateQueries()
      }}
    >
      {other}
    </button>
  )
}
