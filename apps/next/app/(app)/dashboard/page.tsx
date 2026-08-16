import { DashboardOverview } from '@/components/dashboard'

export default function DashboardPage() {
  return (
    <section className="mx-auto w-full max-w-5xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">An overview of your datasets and recent activity.</p>
      </header>
      <DashboardOverview />
    </section>
  )
}
