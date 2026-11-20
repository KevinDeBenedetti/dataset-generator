// The languages of the interface. The choice lives in a cookie (no URL
// prefix): the same address shows the page in the reader's language.
export const LOCALES = ['en', 'fr'] as const
export type Locale = (typeof LOCALES)[number]
export const DEFAULT_LOCALE: Locale = 'en'

// Not httpOnly: the language switcher writes it from the browser. It holds a
// language code and nothing else.
export const LOCALE_COOKIE = 'dg-locale'
export const LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

export function isLocale(value: string | undefined | null): value is Locale {
  return LOCALES.includes(value as Locale)
}

/** The language of a request: the one the reader picked (cookie), else the
 *  first language their browser asks for that the interface has, else English. */
export function pickLocale(
  cookie: string | undefined | null,
  acceptLanguage: string | undefined | null,
): Locale {
  if (isLocale(cookie)) return cookie
  const wanted = (acceptLanguage ?? '')
    .split(',')
    .map((part) => {
      const [tag, ...params] = part.trim().split(';')
      const q = params.map((p) => p.trim()).find((p) => p.startsWith('q='))
      const weight = q ? Number(q.slice(2)) : 1
      return { base: tag.trim().toLowerCase().split('-')[0], weight }
    })
    .filter(({ weight }) => weight > 0)
    .toSorted((a, b) => b.weight - a.weight)
  for (const { base } of wanted) {
    if (isLocale(base)) return base
  }
  return DEFAULT_LOCALE
}

/** The cookie the switcher writes; `secure` outside plain-http development. */
export function localeCookie(locale: Locale, secure: boolean): string {
  return `${LOCALE_COOKIE}=${locale}; Path=/; Max-Age=${LOCALE_COOKIE_MAX_AGE}; SameSite=Lax${
    secure ? '; Secure' : ''
  }`
}
