import type messages from './messages/en.json'
import type { Locale } from './i18n/config'

// Message keys and the locale are type-checked against the English file.
declare module 'next-intl' {
  interface AppConfig {
    Locale: Locale
    Messages: typeof messages
  }
}
