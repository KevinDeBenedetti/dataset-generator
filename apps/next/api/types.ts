// Hand-written, stable re-export of the auto-generated types.
//
// `@hey-api/openapi-ts` writes `types.gen.ts`, so we keep a curated
// `@/api/types` entry point here that survives regeneration. The generator's
// own barrel (`api/index.ts`) is disabled — see `output.entryFile` in
// openapi-ts.config.ts.
export * from './types.gen'
