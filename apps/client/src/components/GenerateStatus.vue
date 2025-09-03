<script setup lang="ts">
import {
  Stepper,
  StepperDescription,
  StepperIndicator,
  StepperItem,
  StepperSeparator,
  StepperTitle,
  StepperTrigger,
} from '@/components/ui/stepper'

import { CircleX, Send, Check } from 'lucide-vue-next'
import { useDatasetStore } from '@/stores/dataset'
import { Loader2 } from 'lucide-vue-next'
import { computed } from 'vue'

const datasetStore = useDatasetStore()

const currentStep = computed(() => {
  // Si clean est en cours ou terminé, on est à l'étape 3
  if (
    datasetStore.cleanStatus === 'pending' ||
    datasetStore.cleanStatus === 'success' ||
    datasetStore.cleanStatus === 'error'
  ) {
    return 3
  }
  // Si analyze est en cours ou terminé, on est à l'étape 2
  if (
    datasetStore.analyzeStatus === 'pending' ||
    datasetStore.analyzeStatus === 'success' ||
    datasetStore.analyzeStatus === 'error'
  ) {
    return 2
  }
  // Si generation est en cours ou terminé, on est à l'étape 1
  if (
    datasetStore.generationStatus === 'pending' ||
    datasetStore.generationStatus === 'success' ||
    datasetStore.generationStatus === 'error'
  ) {
    return 1
  }
  // Par défaut, on est à l'étape 1
  return 1
})
</script>

<template>
  <Stepper class="flex justify-center" :model-value="currentStep">
    <StepperItem :step="1">
      <StepperTrigger>
        <StepperIndicator>
          <Loader2
            v-if="datasetStore.generationStatus === 'pending'"
            class="w-4 h-4 animate-spin"
          />
          <Check
            v-else-if="datasetStore.generationStatus === 'success'"
            class="w-4 h-4 text-green-600"
          />
          <CircleX
            v-else-if="datasetStore.generationStatus === 'error'"
            class="w-4 h-4 text-red-600"
          />
          <Send v-else class="w-4 h-4 text-gray-400" />
        </StepperIndicator>
        <StepperTitle>Generate</StepperTitle>
        <StepperDescription>Scrap & generate from url</StepperDescription>
      </StepperTrigger>
      <StepperSeparator />
    </StepperItem>
    <StepperItem :step="2">
      <StepperTrigger>
        <StepperIndicator>
          <Loader2 v-if="datasetStore.analyzeStatus === 'pending'" class="w-4 h-4 animate-spin" />
          <Check
            v-else-if="datasetStore.analyzeStatus === 'success'"
            class="w-4 h-4 text-green-600"
          />
          <CircleX
            v-else-if="datasetStore.analyzeStatus === 'error'"
            class="w-4 h-4 text-red-600"
          />
          <Send v-else class="w-4 h-4 text-gray-400" />
        </StepperIndicator>
        <StepperTitle>Analyze</StepperTitle>
        <StepperDescription>Analyze the generated content</StepperDescription>
      </StepperTrigger>
      <StepperSeparator />
    </StepperItem>
    <StepperItem :step="3">
      <StepperTrigger>
        <StepperIndicator>
          <Loader2 v-if="datasetStore.cleanStatus === 'pending'" class="w-4 h-4 animate-spin" />
          <Check
            v-else-if="datasetStore.cleanStatus === 'success'"
            class="w-4 h-4 text-green-600"
          />
          <CircleX v-else-if="datasetStore.cleanStatus === 'error'" class="w-4 h-4 text-red-600" />
          <Send v-else class="w-4 h-4 text-gray-400" />
        </StepperIndicator>
        <StepperTitle>Clean</StepperTitle>
        <StepperDescription>Clean the generated content</StepperDescription>
      </StepperTrigger>
    </StepperItem>
  </Stepper>
</template>
