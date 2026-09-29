// Hand-written, stable re-export of the auto-generated types.
//
// `@hey-api/openapi-ts` writes `gen/types.gen.ts` (gitignored, rebuilt on
// every dev/build/typecheck/test), so we keep a curated `@/api/types` entry
// point here. The generator's own barrel is disabled — see `output.entryFile`
// in openapi-ts.config.ts.
export * from './gen/types.gen'
