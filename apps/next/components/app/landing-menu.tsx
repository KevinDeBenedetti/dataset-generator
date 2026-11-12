'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Menu, X } from 'lucide-react'
import { ThemeToggle } from '@/components/app/theme-toggle'

export type LandingLink = { href: string; label: string; external?: boolean }

/** The homepage's section links and theme switch on phones: a button that drops
 *  them below the bar. Picking a link, Escape or a tap outside closes it. */
export function LandingMenu({ links }: { links: LandingLink[] }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [open])

  return (
    <div ref={rootRef} className="md:hidden">
      <button
        type="button"
        aria-label={open ? 'Close the menu' : 'Open the menu'}
        aria-expanded={open}
        aria-controls="landing-menu"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex size-10 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        {open ? <X className="size-5" /> : <Menu className="size-5" />}
      </button>
      {open && (
        <div
          id="landing-menu"
          className="absolute inset-x-0 top-full border-b border-border bg-background px-4 pb-3 pt-1 shadow-lg"
        >
          {links.map(({ href, label, external }) => (
            <Link
              key={label}
              href={href}
              onClick={() => setOpen(false)}
              {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}
              className="block rounded-md px-2 py-3 text-[15px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {label}
            </Link>
          ))}
          <div className="flex items-center justify-between px-2 py-1 text-[15px] text-muted-foreground">
            Theme
            <ThemeToggle className="size-10" />
          </div>
        </div>
      )}
    </div>
  )
}
