/**
 * Liveness endpoint for the `next` container healthcheck (docker-compose):
 * `curl -f http://localhost:${NEXT_PORT}/api/health`. Returns 200 once the
 * Next.js server is serving requests.
 */
export const dynamic = 'force-dynamic'

export function GET() {
  return Response.json({ status: 'ok' })
}
