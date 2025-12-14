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
      // Génère des types plus stricts
      enums: 'typescript',
      tree: true
    },
    {
      name: '@hey-api/sdk',
      // Génère un SDK avec toutes les méthodes
      methodNameBuilder: (operation) => {
        // Personnalise les noms des méthodes
        return `${operation.method}${operation.path.replace(/[{}]/g, 'By').replace(/\//g, '')}`;
      }
    },
    {
        name: '@hey-api/client-axios',
        bundle: true
    }
  ],
});