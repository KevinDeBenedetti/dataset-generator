import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: 'http://localhost:8000/openapi.json',
  output: {
    path: './src/api',
    format: 'prettier',
    lint: 'eslint'
  },
  plugins: [
    {
      name: '@hey-api/typescript',
      // Generate stricter types
      enums: 'typescript',
      tree: true
    },
    {
      name: '@hey-api/sdk',
      // Generate an SDK with all methods
      methodNameBuilder: (operation) => {
        // Customize method names
        return `${operation.method}${operation.path.replace(/[{}]/g, 'By').replace(/\//g, '')}`;
      }
    },
    {
        name: '@hey-api/client-axios',
        bundle: true
    }
  ],
});
