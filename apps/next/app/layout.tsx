import type { Metadata } from 'next'
import { headers } from 'next/headers'
import { GeistMono } from 'geist/font/mono'
import { GeistSans } from 'geist/font/sans'
import './globals.css'
import { Providers } from '@/providers'
import { DevLogConsole } from '@/components/app/dev-log-console'

// Self-hosted (the `geist` package ships the font files): no build-time fetch
// from Google, so builds are reproducible offline and the CSP needs no external
// font origin. Same CSS variables as before.
export const metadata: Metadata = {
  title: 'Dataset Generator',
  description: 'Generate and manage Q&A datasets from URLs',
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  // The CSP nonce set by proxy.ts (production only): our one inline script
  // must carry it or the browser refuses to run it.
  const nonce = (await headers()).get('x-nonce') ?? undefined
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${GeistSans.variable} ${GeistMono.variable} antialiased`}>
        <script
          nonce={nonce}
          // Apply the stored theme before paint to avoid a flash of the wrong theme.
          // Rendered at the top of <body> (not a manual <head>) so Next fully owns
          // head resource management.
          dangerouslySetInnerHTML={{
            __html:
              "try{if(localStorage.getItem('dg-theme')==='dark')document.documentElement.classList.add('dark')}catch(e){}",
          }}
        />
        <Providers>
          <main className="min-h-screen">{children}</main>
          <DevLogConsole />
        </Providers>
      </body>
    </html>
  )
}
