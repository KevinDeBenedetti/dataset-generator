import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from '@/providers'
import { DevLogConsole } from '@/components/app/dev-log-console'

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})

export const metadata: Metadata = {
  title: 'Dataset Generator',
  description: 'Generate and manage Q&A datasets from URLs',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          // Apply the stored theme before paint to avoid a flash of the wrong theme.
          dangerouslySetInnerHTML={{
            __html:
              "try{if(localStorage.getItem('dg-theme')==='dark')document.documentElement.classList.add('dark')}catch(e){}",
          }}
        />
      </head>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>
          <main className="min-h-screen">{children}</main>
          <DevLogConsole />
        </Providers>
      </body>
    </html>
  )
}
