module.exports = {
    root: true,
    extends: [
        '@vue/eslint-config-typescript',
        '@vue/eslint-config-prettier'
    ],
    parserOptions: {
        ecmaVersion: 'latest'
    },
    rules: {
        // Disable the multi-word component names rule for UI components
        'vue/multi-word-component-names': ['error', {
            ignores: [
                'Accordion',
                'Badge',
                'Pagination',
                'Select',
                'Separator',
                'Skeleton',
                'Slider',
                'Stepper'
            ]
        }]
    }
}
