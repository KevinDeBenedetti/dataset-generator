'use client'

import { usePathname } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { AppSidebar } from '@/components/app/app-sidebar'
import { AppTopbar } from '@/components/app/app-topbar'

// Same width as the drawer breakpoint in app-shell.css: below it the sidebar
// is an off-canvas drawer opened from the top bar's menu button.
const DRAWER_QUERY = '(max-width: 920px)'

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [navOpen, setNavOpen] = useState(false)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const wasOpen = useRef(false)

  // Following a link from the drawer lands on another page: close it there.
  const [shownPath, setShownPath] = useState(pathname)
  if (pathname !== shownPath) {
    setShownPath(pathname)
    setNavOpen(false)
  }

  // Focus moves into the drawer when it opens and back to the menu button when
  // it closes; Escape closes it.
  useEffect(() => {
    if (!navOpen) {
      if (wasOpen.current) menuButtonRef.current?.focus()
      wasOpen.current = false
      return
    }
    wasOpen.current = true
    sidebarRef.current?.querySelector<HTMLElement>('.sb-close')?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setNavOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [navOpen])

  // Widening the window past the breakpoint turns the drawer back into the
  // static sidebar: drop the open state so the page is not left inert.
  useEffect(() => {
    const query = window.matchMedia(DRAWER_QUERY)
    const onChange = () => {
      if (!query.matches) setNavOpen(false)
    }
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  return (
    <div className="app">
      <AppSidebar ref={sidebarRef} open={navOpen} onClose={() => setNavOpen(false)} />
      {navOpen && (
        <button
          type="button"
          className="sb-backdrop"
          aria-label="Close navigation"
          tabIndex={-1}
          onClick={() => setNavOpen(false)}
        />
      )}
      <div className="main" inert={navOpen}>
        <AppTopbar
          menuButtonRef={menuButtonRef}
          navOpen={navOpen}
          onOpenNav={() => setNavOpen(true)}
        />
        <div className="content">{children}</div>
      </div>
    </div>
  )
}
