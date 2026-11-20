import { cookies, headers } from 'next/headers'
import { getRequestConfig } from 'next-intl/server'
import { type Locale, LOCALE_COOKIE, pickLocale } from './config'

// One import per language, named: a template import (`../messages/${locale}.json`)
// would bundle every JSON file under messages/, whatever it holds.
const MESSAGES: Record<Locale, () => Promise<{ default: Record<string, unknown> }>> = {
  en: () => import('../messages/en.json'),
  fr: () => import('../messages/fr.json'),
}

// Read by next-intl for every request (next.config.ts points here).
export default getRequestConfig(async () => {
  const locale = pickLocale(
    (await cookies()).get(LOCALE_COOKIE)?.value,
    (await headers()).get('accept-language'),
  )
  return { locale, messages: (await MESSAGES[locale]()).default }
})
