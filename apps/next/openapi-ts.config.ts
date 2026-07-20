// Type-only import on purpose: the generator runs from the pinned sandbox in
// ./openapi-codegen (the project's typescript@7 native compiler no longer
// ships the JS compiler API that @hey-api/openapi-ts needs), and a runtime
// import here would resolve the project-local copy and crash. Type imports
// are erased when the config is loaded.
import type { UserConfig } from '@hey-api/openapi-ts'

const config: UserConfig = {
  // Overridable so `make api-client` can point at a non-default API port
  // (see the dev-port lanes in docker-compose / .env).
  input: process.env.OPENAPI_INPUT ?? 'http://localhost:8000/openapi.json',
  output: {
    path: './api',
    // No prettier/eslint post-processing: the repo lints with oxlint/oxfmt,
    // which both ignore the generated api/**/*.gen.ts files anyway — and
    // neither eslint nor prettier is installed (spawning them would ENOENT).
    // Hand-written files (sdk.ts, types.ts) live alongside the generated
    // *.gen.ts ones in this same directory — the default `clean: true`
    // wipes the whole output dir first and deletes them.
    clean: false,
  },
  plugins: [
    {
      name: '@hey-api/typescript',
      enums: 'typescript',
    },
    {
      name: '@hey-api/sdk',
    },
    {
      name: '@hey-api/client-fetch',
      bundle: true,
    },
  ],
}

export default config
