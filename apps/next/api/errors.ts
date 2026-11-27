// How the API client reports a failed call, and which failures are worth
// asking again. Kept apart from sdk.ts (no generated client here) so it is
// tested on its own.
import type { ValidationError } from './gen/types.gen'

/** A failed API call: the server's message and, when it answered, its status. */
export class ApiError extends Error {
  readonly status: number | undefined

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** A refused sign-in: the API's reason ``code`` (auth/hf_token.py) besides its message. */
export class SignInError extends ApiError {
  readonly code: string | undefined

  constructor(message: string, status?: number, code?: string) {
    super(message, status)
    this.name = 'SignInError'
    this.code = code
  }
}

/** The HTTP status of an error thrown by these wrappers, if it had one. */
export function errorStatus(error: unknown): number | undefined {
  return error instanceof ApiError ? error.status : undefined
}

// A readable message from an API error body. FastAPI returns either
// { detail: string } (our ErrorResponse) or, on a 422,
// { detail: ValidationError[] }. The array case must be flattened to a string,
// otherwise it surfaces as "[object Object]" in the UI.
export function getErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== 'object' || !('detail' in error)) {
    return fallback
  }

  const detail = (error as { detail?: unknown }).detail

  if (typeof detail === 'string') {
    return detail || fallback
  }

  if (Array.isArray(detail)) {
    const messages = (detail as ValidationError[])
      .map((item) => {
        const loc = Array.isArray(item?.loc)
          ? item.loc.filter((part) => part !== 'body').join('.')
          : ''
        const msg = item?.msg ?? ''
        return loc ? `${loc}: ${msg}` : String(msg)
      })
      .filter(Boolean)
    if (messages.length) {
      return messages.join('; ')
    }
  }

  return fallback
}

/** The ApiError of a failed call of the generated client. */
export function apiError(
  result: { error?: unknown; response?: Response },
  fallback: string,
): ApiError {
  return new ApiError(getErrorMessage(result.error, fallback), result.response?.status)
}

// This API's definitive answers: asking again changes nothing. Every 4xx but a
// request timeout. A 5xx is retried, 503 included: the API sends it for a
// feature that isn't configured, but a proxy sends it during a deployment too.
function definitive(status: number): boolean {
  return status >= 400 && status < 500 && status !== 408
}

/** The retry policy of every query (providers/query-provider.tsx): a server
 *  or network failure is asked again twice; a definitive answer is not. */
export function retryTransient(failureCount: number, error: Error): boolean {
  const status = errorStatus(error)
  return !(status != null && definitive(status)) && failureCount < 2
}
