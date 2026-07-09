import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: 'http://localhost:8000/openapi.json',
  output: {
    path: './api',
    format: 'prettier',
    lint: 'eslint',
    // Hand-written files (sdk.ts, types.ts) live alongside the generated
    // *.gen.ts ones in this same directory — the default `clean: true`
    // wipes the whole output dir first and deletes them.
    clean: false
  },
  plugins: [
    {
      name: '@hey-api/typescript',
      enums: 'typescript'
    },
    {
      name: '@hey-api/sdk'
    },
    {
      name: '@hey-api/client-fetch',
      bundle: true
    }
  ],
});
