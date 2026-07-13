'use client'

import { useSyncExternalStore } from 'react'

function subscribe(callback: () => void) {
  const observer = new MutationObserver(callback)
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class'],
  })
  return () => observer.disconnect()
}

/**
 * Reactively tracks whether the `dark` class is set on <html>. Returns false
 * during SSR so server and first client render agree, then syncs to the real
 * DOM state (and any later theme changes) on the client.
 */
export function useIsDark() {
  return useSyncExternalStore(
    subscribe,
    () => document.documentElement.classList.contains('dark'),
    () => false,
  )
}
