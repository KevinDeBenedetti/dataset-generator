import type { NextConfig } from 'next'

// Where the API lives, for the /api rewrite below (server-side only).
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || 'http://localhost:8000'

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,

  // `next build` emits a self-contained server (.next/standalone) for the
  // production image; `next dev` is unaffected.
  output: 'standalone',

  // Same-origin API access: in production the browser calls `/api/*`. The
  // ingress normally routes that straight to the API before it reaches Next;
  // this rewrite is the fallback for a plain `next start` (and it never shadows
  // Next's own route handlers, which match first).
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${API_INTERNAL_URL}/:path*` }]
  },

  // The Content-Security-Policy (needs a per-request nonce) is set in proxy.ts.
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=(), payment=()',
          },
          ...(process.env.NODE_ENV === 'production'
            ? [
                {
                  key: 'Strict-Transport-Security',
                  value: 'max-age=63072000; includeSubDomains',
                },
              ]
            : []),
        ],
      },
    ]
  },
}

export default nextConfig
