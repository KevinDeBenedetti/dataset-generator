'use client'

import { Moon, Sun } from 'lucide-react'
import { cn, toggleTheme } from '@/lib/utils'
import { useIsDark } from '@/hooks/use-is-dark'

export function ThemeToggle({ className }: { className?: string }) {
  const dark = useIsDark()

  return (
    <button
      type="button"
      onClick={toggleTheme}
      title="Theme"
      aria-label="Toggle theme"
      className={cn(
        'inline-flex size-[34px] items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
        className,
      )}
    >
      {dark ? <Moon className="size-[17px]" /> : <Sun className="size-[17px]" />}
    </button>
  )
}
