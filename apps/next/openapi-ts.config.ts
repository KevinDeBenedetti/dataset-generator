// Type-only import on purpose: the generator runs from the pinned sandbox in
// ./openapi-codegen (the project's typescript@7 native compiler no longer
// ships the JS compiler API that @hey-api/openapi-ts needs), and a runtime
// import here would resolve the project-local copy and crash. Type imports
// are erased when the config is loaded.
import type { UserConfig } from '@hey-api/openapi-ts'

const config: UserConfig = {
  // Overridable so `make api-client` can point at a non-default API port
  // (see the dev-port lanes in docker-compose / .env), and so `make api-check`
  // can feed it a schema file dumped straight from the app, with no server.
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
    // Don't emit api/index.ts. The generator's barrel re-exports the raw
    // sdk.gen/types.gen surface, which nothing imports: the app goes through the
    // hand-written wrappers (`@/api/sdk`, `@/api/types`). Generating it only
    // created a second, unwrapped way to call the API — one that bypasses the
    // silent session refresh in sdk.ts.
    entryFile: false,
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
      // Don't bake a base URL into client.gen.ts. The generator would otherwise
      // infer it from `input` — freezing whichever host/port the person who ran
      // the generator happened to use, and making the output differ between a
      // URL input and a file input (which would break `make api-check`).
      // api/sdk.ts sets the real base URL at runtime from
      // NEXT_PUBLIC_API_BASE_URL.
      baseUrl: false,
    },
  ],
}

export default config
