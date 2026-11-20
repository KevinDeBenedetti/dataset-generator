import { useTranslations } from 'next-intl'

interface ErrorStateProps {
  message?: string
}

export function ErrorState({ message }: ErrorStateProps) {
  const t = useTranslations('generate.error')
  return (
    <div className="text-center p-8 text-red-500">
      <p className="text-lg">{t('title')}</p>
      <p className="text-sm mt-2">{message ?? t('fallback')}</p>
    </div>
  )
}
