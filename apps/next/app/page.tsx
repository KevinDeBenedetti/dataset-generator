import Link from 'next/link'
import {
  ArrowRight,
  Command,
  CopyCheck,
  Download,
  FileJson,
  FilterX,
  GitBranch,
  Globe,
  Languages,
  LayoutDashboard,
  Layers,
  ShieldCheck,
  Sparkles,
  Table,
  Zap,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ThemeToggle } from '@/components/app/theme-toggle'

const GITHUB_URL = 'https://github.com/KevinDeBenedetti/dataset-generator'

const features = [
  {
    icon: Globe,
    title: 'Multi-source scraping',
    description:
      'URL, sitemap, RSS feed or file upload. Automatic content fetching and normalization.',
  },
  {
    icon: Sparkles,
    title: 'LLM Q/A generation',
    description:
      'Configurable prompts, your choice of models, and question-answer pairs grounded in the source.',
  },
  {
    icon: CopyCheck,
    title: 'Duplicate detection',
    description: 'Semantic similarity filters out redundancy before pairs reach your dataset.',
  },
  {
    icon: Languages,
    title: 'Multi-language',
    description: 'Generation in French, English, Spanish and German, with localized prompts.',
  },
  {
    icon: ShieldCheck,
    title: 'Quality control',
    description: 'Automatic validation and filtering, quality scores and configurable thresholds.',
  },
  {
    icon: Command,
    title: 'REST API',
    description: 'Programmatic access to embed generation into your own workflows.',
  },
]

const steps = [
  { num: '01', icon: Globe, title: 'Scraping', description: 'Fetch raw web data.' },
  {
    num: '02',
    icon: FilterX,
    title: 'Cleaning',
    description: 'Normalize, extract the useful content.',
  },
  {
    num: '03',
    icon: Sparkles,
    title: 'Generation',
    description: 'Q/A pairs via LLM and prompts.',
  },
  {
    num: '04',
    icon: ShieldCheck,
    title: 'Quality',
    description: 'Validation and deduplication.',
  },
  {
    num: '05',
    icon: Download,
    title: 'Export',
    description: 'Langfuse, JSON, CSV, JSONL.',
  },
  {
    num: '06',
    icon: GitBranch,
    title: 'Versioning',
    description: 'Storage and metadata tracking.',
  },
]

const formats = [
  { icon: Zap, name: 'Langfuse', description: 'Training-data management' },
  { icon: FileJson, name: 'JSON / JSONL', description: 'Standard data interchange' },
  { icon: Table, name: 'CSV', description: 'Tabular analysis and review' },
  { icon: Command, name: 'REST API', description: 'Extensible custom formats' },
]

function Brand() {
  return (
    <span className="flex items-center gap-2.5 font-semibold">
      <span className="flex size-[26px] items-center justify-center rounded-md bg-primary text-primary-foreground">
        <Layers className="size-4" />
      </span>
      Dataset<span className="opacity-50">Gen</span>
    </span>
  )
}

export default function HomePage() {
  return (
    <>
      {/* Landing navigation */}
      <nav className="sticky top-0 z-30 h-[60px] border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex h-full w-full max-w-[1080px] items-center gap-3.5 px-7">
          <Link href="/">
            <Brand />
          </Link>
          <div className="ml-[18px] hidden gap-1 md:flex">
            {[
              { href: '#features', label: 'Features' },
              { href: '#workflow', label: 'Pipeline' },
              { href: '#formats', label: 'Exports' },
              { href: GITHUB_URL, label: 'Docs' },
            ].map(({ href, label }) => (
              <Link
                key={label}
                href={href}
                className="rounded-md px-2.5 py-[7px] text-[13.5px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                {label}
              </Link>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <Button asChild size="sm" variant="ghost">
              <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                <GitBranch className="size-4" />
                GitHub
              </a>
            </Button>
            <Button asChild size="sm">
              <Link href="/dashboard">
                Open the dashboard
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
        </div>
      </nav>

      <div className="mx-auto max-w-[1080px] px-7">
        {/* Hero */}
        <header className="pb-14 pt-[78px]">
          <div className="inline-flex h-7 items-center gap-2 rounded-full border border-border bg-card pl-2 pr-3 text-[12.5px] text-muted-foreground">
            <span className="inline-flex h-[17px] items-center gap-1.5 rounded-full border border-success/30 bg-success/15 px-2 text-[10.5px] font-medium text-success">
              <span className="size-1.5 rounded-full bg-current" />
              v0.7.7
            </span>
            Scraping → LLM → dataset pipeline, open-source
          </div>
          <h1 className="mt-[22px] max-w-[16ch] text-[38px] font-semibold leading-[1.04] tracking-[-0.035em] sm:text-[52px]">
            Clean Q/A datasets,{' '}
            <span className="text-muted-foreground">straight from the web.</span>
          </h1>
          <p className="mt-5 max-w-[56ch] text-[17px] leading-[1.55] text-muted-foreground">
            Scrape reliable sources, generate context-aware question-answer pairs with an LLM, catch
            duplicates, and export to Langfuse, JSONL or CSV — all from a single interface.
          </p>
          <div className="mt-[30px] flex flex-wrap gap-[11px]">
            <Button asChild size="lg">
              <Link href="/generate">
                <Sparkles className="size-4" />
                Generate a dataset
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/dashboard">
                <LayoutDashboard className="size-4" />
                View the dashboard
              </Link>
            </Button>
          </div>
          <div className="mt-[34px] flex flex-wrap gap-[22px] text-[13px] text-muted-foreground">
            <div>
              <b className="font-semibold tabular-nums text-foreground">4</b> languages — FR · EN ·
              ES · DE
            </div>
            <div>
              <b className="font-semibold tabular-nums text-foreground">70%+</b> test coverage
            </div>
            <div>
              <b className="font-semibold text-foreground">FastAPI</b> + Next.js
            </div>
          </div>
        </header>

        {/* Terminal */}
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-lg">
          <div className="flex h-[38px] items-center gap-2 border-b border-border bg-muted px-3.5">
            <span className="size-[11px] rounded-full bg-border" />
            <span className="size-[11px] rounded-full bg-border" />
            <span className="size-[11px] rounded-full bg-border" />
            <span className="ml-2 font-mono text-xs text-muted-foreground">
              ~/dataset-generator — make start
            </span>
          </div>
          <pre className="overflow-x-auto whitespace-pre px-5 py-[18px] font-mono text-[13px] leading-[1.85]">
            <span className="text-muted-foreground"># Run the pipeline on a source</span>
            {'\n'}
            <span className="text-success">$</span> <span className="text-info">datasetgen</span>{' '}
            generate <span className="text-warning">--url</span> https://docs.example.com{' '}
            <span className="text-warning">--lang</span> en{' '}
            <span className="text-warning">--n</span> 50{'\n'}
            <span className="text-muted-foreground">→ scraping </span>{' '}
            <span className="text-success">12 pages · 48,320 tokens</span>
            {'\n'}
            <span className="text-muted-foreground">→ cleaning </span>{' '}
            <span className="text-success">normalized · 9,540 tokens kept</span>
            {'\n'}
            <span className="text-muted-foreground">→ qa-generation</span>{' '}
            <span className="text-success">50 Q/A pairs · gpt-4o-mini</span>
            {'\n'}
            <span className="text-muted-foreground">→ dedup </span>{' '}
            <span className="text-success">3 duplicates removed (cosine ≥ 0.92)</span>
            {'\n'}
            <span className="text-muted-foreground">→ export </span>{' '}
            <span className="text-success">langfuse · dataset &quot;docs-en&quot; #v4</span>
            {'\n'}
            <span className="text-success">✓</span> dataset ready —{' '}
            <span className="text-info">47 pairs</span> · quality{' '}
            <span className="text-success">94%</span>
          </pre>
        </div>

        {/* Features */}
        <section id="features" className="scroll-mt-20 border-t border-border py-14">
          <div className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
            {'// features'}
          </div>
          <h2 className="mt-3 max-w-[20ch] text-3xl font-semibold tracking-[-0.03em]">
            The whole pipeline, without gluing scripts together.
          </h2>
          <p className="mt-3 max-w-[58ch] text-[15px] text-muted-foreground">
            Each step is a module: scraper, LLM client, data manager, export. Compose them from the
            UI or the REST API.
          </p>
          <div className="mt-[34px] grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {features.map(({ icon: Icon, title, description }) => (
              <div
                key={title}
                className="rounded-[10px] border border-border bg-card p-[22px] shadow-xs"
              >
                <div className="flex size-[38px] items-center justify-center rounded-[9px] bg-secondary text-muted-foreground">
                  <Icon className="size-[19px]" />
                </div>
                <h3 className="mt-4 text-[15.5px] font-semibold">{title}</h3>
                <p className="mt-[7px] text-[13.5px] leading-[1.55] text-muted-foreground">
                  {description}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Workflow */}
        <section id="workflow" className="scroll-mt-20 border-t border-border py-14">
          <div className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
            {'// pipeline'}
          </div>
          <h2 className="mt-3 max-w-[20ch] text-3xl font-semibold tracking-[-0.03em]">
            Six steps, from raw page to versioned dataset.
          </h2>
          <div className="mt-9 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-3 md:grid-cols-6">
            {steps.map(({ num, icon: Icon, title, description }) => (
              <div key={num} className="bg-card p-5">
                <div className="font-mono text-xs text-muted-foreground">{num}</div>
                <Icon className="mt-3.5 size-[18px]" />
                <h4 className="mt-2.5 text-[13.5px] font-semibold">{title}</h4>
                <p className="mt-1 text-xs leading-[1.5] text-muted-foreground">{description}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Formats */}
        <section id="formats" className="scroll-mt-20 border-t border-border py-14">
          <div className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
            {'// exports'}
          </div>
          <h2 className="mt-3 max-w-[20ch] text-3xl font-semibold tracking-[-0.03em]">
            Send your data wherever you need it.
          </h2>
          <div className="mt-[30px] grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
            {formats.map(({ icon: Icon, name, description }) => (
              <div
                key={name}
                className="flex items-center gap-3 rounded-[10px] border border-border bg-card p-4 shadow-xs"
              >
                <Icon className="size-5 text-muted-foreground" />
                <div>
                  <b className="font-mono text-[13.5px] font-semibold">{name}</b>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{description}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section className="border-t border-border py-14">
          <div className="rounded-2xl border border-border bg-card p-11 text-center">
            <h2 className="text-[28px] font-semibold tracking-[-0.03em]">
              Build your first dataset in minutes.
            </h2>
            <p className="mx-auto mt-3 max-w-[48ch] text-muted-foreground">
              Pick a source, run the pipeline, review the Q/A pairs and export. Without leaving the
              interface.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-[11px]">
              <Button asChild size="lg">
                <Link href="/generate">
                  <Sparkles className="size-4" />
                  Start generating
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline">
                <Link href="/datasets">Browse datasets</Link>
              </Button>
            </div>
          </div>
        </section>
      </div>

      {/* Footer */}
      <footer className="border-t border-border pb-16 pt-[34px]">
        <div className="mx-auto max-w-[1080px] px-7">
          <div className="flex flex-wrap justify-between gap-[30px] text-[13px]">
            <div className="max-w-[280px]">
              <Link href="/">
                <Brand />
              </Link>
              <p className="mt-3 text-[13px] leading-[1.6] text-muted-foreground">
                Automated question-answer dataset generation via web scraping and LLMs. Duplicate
                detection and Langfuse export.
              </p>
            </div>
            <FooterCol
              title="Product"
              links={[
                { href: '/dashboard', label: 'Dashboard' },
                { href: '/generate', label: 'Generate' },
                { href: '/datasets', label: 'Datasets' },
                { href: '/agent-test', label: 'Verify QA' },
              ]}
            />
            <FooterCol
              title="Resources"
              links={[
                { href: GITHUB_URL, label: 'Documentation' },
                { href: GITHUB_URL, label: 'GitHub' },
                { href: GITHUB_URL, label: 'REST API' },
                { href: '#', label: 'Changelog' },
              ]}
            />
            <FooterCol
              title="Legal"
              links={[
                { href: '#', label: 'Legal notice' },
                { href: '#', label: 'Privacy' },
                { href: '#', label: 'Terms' },
              ]}
            />
          </div>
          <div className="mt-9 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5 text-[12.5px] text-muted-foreground">
            <span>© 2026 DatasetGen. Open-source licensed.</span>
            <span className="font-mono">Python · FastAPI · Next.js · shadcn/ui</span>
          </div>
        </div>
      </footer>
    </>
  )
}

function FooterCol({ title, links }: { title: string; links: { href: string; label: string }[] }) {
  return (
    <div className="text-[13px]">
      <h5 className="mb-3 text-xs font-medium uppercase tracking-[0.06em] text-muted-foreground">
        {title}
      </h5>
      {links.map(({ href, label }) => (
        <Link
          key={label}
          href={href}
          className="block py-[5px] text-muted-foreground transition-colors hover:text-foreground"
        >
          {label}
        </Link>
      ))}
    </div>
  )
}
