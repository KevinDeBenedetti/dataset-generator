import { useTranslations } from 'next-intl'
import { DashboardOverview } from '@/components/dashboard'

export default function DashboardPage() {
  const t = useTranslations('dashboard')
  return (
    <section className="mx-auto w-full max-w-5xl py-2 sm:px-4 sm:py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">{t('title')}</h1>
        <p className="text-muted-foreground">{t('subtitle')}</p>
      </header>
      <DashboardOverview />
    </section>
  )
}
