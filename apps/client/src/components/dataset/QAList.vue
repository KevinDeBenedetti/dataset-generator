<script setup lang="ts">
import { Accordion } from '@/components/ui/accordion'
import QAItem from './QAItem.vue'

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
  qaData: QA[]
  returnedCount: number
}

defineProps<Props>()
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h3 class="text-lg font-medium">Questions & Réponses</h3>
      <span class="text-sm text-gray-500">
        {{ returnedCount }} question(s)-réponse(s) trouvée(s)
      </span>
    </div>

    <div v-if="qaData && qaData.length > 0">
      <Accordion type="single" collapsible class="space-y-2">
        <QAItem
          v-for="(qa, index) in qaData"
          :key="qa.id"
          :qa="qa"
          :index="index"
          :value="`item-${index}`"
        />
      </Accordion>
    </div>

    <div v-else class="text-center py-8 text-gray-500">
      Aucune question-réponse trouvée pour ce dataset.
    </div>
  </div>
</template>
