/**
 * Type definitions to replace 'any' usages in the codebase
 */

// For the generate store
export interface GenerateOptions {
  [key: string]: string | number | boolean | object
}

// For dataset.ts
export interface DatasetRecord {
  [key: string]: string | number | boolean | object | null
}

// For qa.ts
export interface QAResponse {
  [key: string]: string | number | boolean | object | null
}
