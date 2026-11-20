import { useTranslations } from 'next-intl'

export function EmptyState() {
  const t = useTranslations('generate.empty')
  return (
    <div className="text-center p-8 text-gray-500">
      <p className="text-lg">{t('title')}</p>
      <p className="text-sm mt-2">{t('hint')}</p>
    </div>
  )
}
