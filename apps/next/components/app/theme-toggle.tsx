'use client'

import { Moon, Sun } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { cn, toggleTheme } from '@/lib/utils'
import { useIsDark } from '@/hooks/use-is-dark'

export function ThemeToggle({ className }: { className?: string }) {
  const dark = useIsDark()
  const t = useTranslations('theme')

  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={t('label')}
      aria-label={t('toggle')}
      className={cn(
        'inline-flex size-[34px] items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
        className,
      )}
    >
      {dark ? <Moon className="size-[17px]" /> : <Sun className="size-[17px]" />}
    </button>
  )
}
