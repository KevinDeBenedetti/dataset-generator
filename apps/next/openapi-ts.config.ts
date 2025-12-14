import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: 'http://localhost:8000/openapi.json',
  output: {
    path: './api',
    format: 'prettier',
    lint: 'eslint'
  },
  plugins: [
    {
      name: '@hey-api/typescript',
      enums: 'typescript'
    },
    {
      name: '@hey-api/sdk',
      methodNameBuilder: (operation) => {
        return `${operation.method}${operation.path.replace(/[{}]/g, 'By').replace(/\//g, '')}`;
      }
    },
    {
      name: '@hey-api/client-fetch',
      bundle: true
    }
  ],
});
