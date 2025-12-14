import { createClient, type Client } from '@hey-api/client-fetch'

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export const client: Client = createClient({
  baseUrl,
})

export { baseUrl }
