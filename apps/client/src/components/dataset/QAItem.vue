<script setup lang="ts">
import { AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { useTextUtils } from '@/composables/useTextUtils'
import type { QAItem } from '@/types/qa'

const props = defineProps<{ qa: QAItem; index: number; value: string }>()

const { truncateText } = useTextUtils()

const toggleContextExpansion = (event: MouseEvent) => {
  const btn = event.currentTarget as HTMLElement
  const contextElement = btn.closest('.relative')?.querySelector('p') as HTMLElement | null
  if (contextElement) {
    contextElement.classList.toggle('max-h-32')
    contextElement.classList.toggle('overflow-hidden')
    btn.textContent = contextElement.classList.contains('max-h-32') ? 'Voir plus' : 'Voir moins'
  }
}
</script>

<template>
  <AccordionItem :value="props.value" class="border border-gray-200 rounded-lg overflow-hidden">
    <AccordionTrigger class="px-4 py-3 hover:bg-gray-50 text-left">
      <div class="flex-1 space-y-2">
        <div class="font-medium text-gray-900">
          Q{{ props.index + 1 }}: {{ truncateText(props.qa.question, 80) }}
        </div>

        <div class="flex flex-wrap gap-3 text-xs text-gray-500">
          <span v-if="props.qa.confidence" class="bg-blue-100 px-2 py-1 rounded">
            Confiance: {{ (props.qa.confidence * 100).toFixed(1) }}%
          </span>
          <span class="bg-gray-100 px-2 py-1 rounded"> ID: {{ props.qa.id.substring(0, 8) }}... </span>
          <span v-if="props.qa.created_at" class="bg-green-100 px-2 py-1 rounded">
            {{ new Date(props.qa.created_at).toLocaleDateString('fr-FR') }}
          </span>
        </div>
      </div>
    </AccordionTrigger>

    <AccordionContent class="px-4 pb-4">
      <div class="space-y-4">
        <!-- Question complète -->
        <div class="bg-blue-50 p-3 rounded-lg">
          <h4 class="font-medium text-blue-900 mb-2 flex items-center">
            <span class="w-2 h-2 bg-blue-500 rounded-full mr-2"></span>
            Question
          </h4>
          <p class="text-blue-800">{{ props.qa.question }}</p>
        </div>

        <!-- Réponse -->
        <div class="bg-green-50 p-3 rounded-lg">
          <h4 class="font-medium text-green-900 mb-2 flex items-center">
            <span class="w-2 h-2 bg-green-500 rounded-full mr-2"></span>
            Réponse
          </h4>
          <p class="text-green-800">{{ props.qa.answer }}</p>
        </div>

        <!-- Contexte -->
        <div v-if="props.qa.context" class="bg-gray-50 p-3 rounded-lg">
          <h4 class="font-medium text-gray-900 mb-2 flex items-center">
            <span class="w-2 h-2 bg-gray-500 rounded-full mr-2"></span>
            Contexte
          </h4>
          <div class="relative">
            <p
              class="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap"
              :class="{ 'max-h-32 overflow-hidden': props.qa.context && props.qa.context.length > 300 }"
            >
              {{ props.qa.context }}
            </p>

            <div
              v-if="props.qa.context && props.qa.context.length > 300"
              class="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-gray-50 to-transparent flex items-end justify-center"
            >
              <button
                @click="toggleContextExpansion"
                class="text-xs bg-white border border-gray-300 px-2 py-1 rounded hover:bg-gray-100"
              >
                Voir plus
              </button>
            </div>
          </div>
        </div>

        <!-- Métadonnées -->
        <div class="bg-yellow-50 p-3 rounded-lg">
          <h4 class="font-medium text-yellow-900 mb-2 flex items-center">
            <span class="w-2 h-2 bg-yellow-500 rounded-full mr-2"></span>
            Informations supplémentaires
          </h4>
          <div class="space-y-2 text-sm">
            <div v-if="props.qa.source_url" class="flex items-start gap-2">
              <span class="font-medium text-yellow-800 min-w-0">Source:</span>
              <a
                :href="props.qa.source_url"
                target="_blank"
                class="text-blue-600 hover:underline break-all"
              >
                {{ props.qa.source_url }}
              </a>
            </div>
            <div class="flex gap-2">
              <span class="font-medium text-yellow-800">ID complet:</span>
              <span class="font-mono text-xs bg-white px-2 py-1 rounded border">{{ props.qa.id }}</span>
            </div>
            <div v-if="props.qa.metadata" class="flex gap-2">
              <span class="font-medium text-yellow-800">Métadonnées:</span>
              <pre class="text-xs bg-white p-2 rounded border overflow-x-auto">{{
                JSON.stringify(props.qa.metadata, null, 2)
              }}</pre>
            </div>
          </div>
        </div>
      </div>
    </AccordionContent>
  </AccordionItem>
</template>
