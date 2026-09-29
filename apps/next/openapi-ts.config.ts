// Type-only import on purpose: the generator runs from the pinned sandbox in
// ./openapi-codegen (the project's typescript@7 native compiler no longer
// ships the JS compiler API that @hey-api/openapi-ts needs), and a runtime
// import here would resolve the project-local copy and crash. Type imports
// are erased when the config is loaded.
import type { UserConfig } from '@hey-api/openapi-ts'

// The committed schema (`make api-schema`) by default, so every build is
// reproducible from the repo alone. `bun run api:watch` points it at the live
// server instead — the generator only watches URLs, not files.
const inputPath = process.env.OPENAPI_INPUT ?? './openapi.json'

const config: UserConfig = {
  input: process.env.OPENAPI_WATCH ? { path: inputPath, watch: true } : inputPath,
  output: {
    // Gitignored and rebuilt by `bun run dev|build|typecheck|test` — treated as
    // a dependency, never edited. The hand-written wrappers (sdk.ts, types.ts)
    // live one level up, so wiping this directory on each run is safe.
    path: './api/gen',
    // No prettier/eslint post-processing: the repo lints with oxlint/oxfmt,
    // which both ignore api/gen — and neither eslint nor prettier is
    // installed (spawning them would ENOENT).
    clean: true,
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
      // URL input (`api:watch`) and the committed file (every build).
      // api/sdk.ts sets the real base URL at runtime from
      // NEXT_PUBLIC_API_BASE_URL.
      baseUrl: false,
    },
  ],
}

export default config
