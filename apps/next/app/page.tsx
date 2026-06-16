import Link from 'next/link'
import {
  Globe,
  Sparkles,
  Tags,
  CopyCheck,
  Bot,
  Download,
  ArrowRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'

const features = [
  {
    icon: Globe,
    title: 'Scrape any URL',
    description:
      'Point it at a web page and the content is fetched and cleaned into plain, structured text — ready to learn from.',
  },
  {
    icon: Bot,
    title: 'AI agents (Google ADK)',
    description:
      'A Google ADK agent drives the language model to craft varied, high-quality question-answer pairs from the source.',
  },
  {
    icon: Tags,
    title: 'Rich metadata',
    description:
      'Every pair ships with the supporting context, source URL, confidence score, timestamps and content hashes.',
  },
  {
    icon: CopyCheck,
    title: 'Similarity detection',
    description:
      'Built-in duplicate and near-duplicate detection keeps your dataset clean, with a configurable similarity threshold.',
  },
  {
    icon: Sparkles,
    title: 'Quality first',
    description:
      'Questions are varied and precise, answers are complete, and trivial or generic pairs are filtered out.',
  },
  {
    icon: Download,
    title: 'Export ready',
    description:
      'Manage your datasets and export them — including to Langfuse — for training and evaluation workflows.',
  },
]

const steps = [
  {
    title: 'Paste a URL',
    description: 'Choose the page, target language and similarity threshold.',
  },
  {
    title: 'Generate',
    description:
      'The agent scrapes, cleans, and produces Q/A pairs with full metadata.',
  },
  {
    title: 'Review & export',
    description:
      'Inspect pairs, prune duplicates, and export a clean dataset.',
  },
]

export default function HomePage() {
  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-4 py-20 text-center">
        <span className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm text-muted-foreground">
          <Sparkles className="size-4" />
          Powered by AI agents
        </span>
        <h1 className="text-balance text-4xl font-bold tracking-tight sm:text-5xl">
          Build quality Q/A datasets from any URL
        </h1>
        <p className="text-balance max-w-2xl text-lg text-muted-foreground">
          A dataset generator that turns web pages into high-quality
          question-answer pairs — complete with the context, metadata and
          similarity checks you need for a training-ready dataset.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Button asChild size="lg">
            <Link href="/generate">
              Generate a dataset
              <ArrowRight className="size-4" />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/datasets">Browse datasets</Link>
          </Button>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto w-full max-w-5xl px-4 pb-16">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map(({ icon: Icon, title, description }) => (
            <Card key={title}>
              <CardHeader>
                <div className="mb-2 flex size-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Icon className="size-5" />
                </div>
                <CardTitle>{title}</CardTitle>
                <CardDescription>{description}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="mx-auto w-full max-w-5xl px-4 pb-20">
        <h2 className="mb-8 text-center text-2xl font-semibold">How it works</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {steps.map(({ title, description }, index) => (
            <Card key={title}>
              <CardHeader>
                <div className="mb-2 flex size-8 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {index + 1}
                </div>
                <CardTitle className="text-lg">{title}</CardTitle>
                <CardDescription>{description}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
        <div className="mt-10 flex justify-center">
          <Button asChild size="lg">
            <Link href="/generate">
              Get started
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
      </section>
    </div>
  )
}
