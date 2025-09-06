<script setup lang="ts">
import { ref } from 'vue'
import { AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { useTextUtils } from '@/composables/useTextUtils'

interface QA {
  id: string
  question: string
  answer: string
  context?: string
  confidence?: number
  created_at?: string
  source_url?: string
  metadata?: any
}

interface Props {
  qa: QA
  index: number
  value: string
}

defineProps<Props>()

const { truncateText } = useTextUtils()

const toggleContextExpansion = (event: Event) => {
  const target = event.target as HTMLElement
  const contextElement = target.closest('.relative')?.querySelector('p') as HTMLElement
  if (contextElement) {
    contextElement.classList.toggle('max-h-32')
    contextElement.classList.toggle('overflow-hidden')
    target.textContent = contextElement.classList.contains('max-h-32') ? 'Voir plus' : 'Voir moins'
  }
}
</script>

<template>
  <AccordionItem :value="value" class="border border-gray-200 rounded-lg overflow-hidden">
    <AccordionTrigger class="px-4 py-3 hover:bg-gray-50 text-left">
      <div class="flex-1 space-y-2">
        <div class="font-medium text-gray-900">
          Q{{ index + 1 }}: {{ truncateText(qa.question, 80) }}
        </div>

        <div class="flex flex-wrap gap-3 text-xs text-gray-500">
          <span v-if="qa.confidence" class="bg-blue-100 px-2 py-1 rounded">
            Confiance: {{ (qa.confidence * 100).toFixed(1) }}%
          </span>
          <span class="bg-gray-100 px-2 py-1 rounded"> ID: {{ qa.id.substring(0, 8) }}... </span>
          <span v-if="qa.created_at" class="bg-green-100 px-2 py-1 rounded">
            {{ new Date(qa.created_at).toLocaleDateString('fr-FR') }}
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
          <p class="text-blue-800">{{ qa.question }}</p>
        </div>

        <!-- Réponse -->
        <div class="bg-green-50 p-3 rounded-lg">
          <h4 class="font-medium text-green-900 mb-2 flex items-center">
            <span class="w-2 h-2 bg-green-500 rounded-full mr-2"></span>
            Réponse
          </h4>
          <p class="text-green-800">{{ qa.answer }}</p>
        </div>

        <!-- Contexte -->
        <div v-if="qa.context" class="bg-gray-50 p-3 rounded-lg">
          <h4 class="font-medium text-gray-900 mb-2 flex items-center">
            <span class="w-2 h-2 bg-gray-500 rounded-full mr-2"></span>
            Contexte
          </h4>
          <div class="relative">
            <p
              class="text-gray-700 text-sm leading-relaxed whitespace-pre-wrap"
              :class="{ 'max-h-32 overflow-hidden': qa.context.length > 300 }"
            >
              {{ qa.context }}
            </p>

            <div
              v-if="qa.context.length > 300"
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
            <div v-if="qa.source_url" class="flex items-start gap-2">
              <span class="font-medium text-yellow-800 min-w-0">Source:</span>
              <a
                :href="qa.source_url"
                target="_blank"
                class="text-blue-600 hover:underline break-all"
              >
                {{ qa.source_url }}
              </a>
            </div>
            <div class="flex gap-2">
              <span class="font-medium text-yellow-800">ID complet:</span>
              <span class="font-mono text-xs bg-white px-2 py-1 rounded border">{{ qa.id }}</span>
            </div>
            <div v-if="qa.metadata" class="flex gap-2">
              <span class="font-medium text-yellow-800">Métadonnées:</span>
              <pre class="text-xs bg-white p-2 rounded border overflow-x-auto">{{
                JSON.stringify(qa.metadata, null, 2)
              }}</pre>
            </div>
          </div>
        </div>
      </div>
    </AccordionContent>
  </AccordionItem>
</template>
