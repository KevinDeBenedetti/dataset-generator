import { globalIgnores } from 'eslint/config'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'
import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'

// To allow more languages other than `ts` in `.vue` files, uncomment the following lines:
// import { configureVueProject } from '@vue/eslint-config-typescript'
// configureVueProject({ scriptLangs: ['ts', 'tsx'] })
// More info at https://github.com/vuejs/eslint-config-typescript/#advanced-setup

export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{ts,mts,tsx,vue}'],
  },

  globalIgnores(['**/dist/**', '**/dist-ssr/**', '**/coverage/**', '**/src/api/**']),

  // Base configurations
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  skipFormatting,

  // Custom rules
  {
    rules: {
      // Allow single-word component names for UI components
      'vue/multi-word-component-names': [
        'error',
        {
          ignores: [
            'Accordion',
            'Badge',
            'Pagination',
            'Select',
            'Separator',
            'Skeleton',
            'Slider',
            'Stepper',
          ],
        },
      ],
    },
  },
)
