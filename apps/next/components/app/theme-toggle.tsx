'use client'

import { Moon, Sun } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useIsDark } from '@/hooks/use-is-dark'

export function ThemeToggle({ className }: { className?: string }) {
  const dark = useIsDark()

  function toggle() {
    const next = !document.documentElement.classList.contains('dark')
    document.documentElement.classList.toggle('dark', next)
    try {
      localStorage.setItem('dg-theme', next ? 'dark' : 'light')
    } catch {
      // ignore storage errors (private mode, etc.)
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      title="Theme"
      aria-label="Toggle theme"
      className={cn(
        'inline-flex size-[34px] items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
        className
      )}
    >
      {dark ? <Moon className="size-[17px]" /> : <Sun className="size-[17px]" />}
    </button>
  )
}
