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

import { Loader, CircleX, Send, Check } from "lucide-vue-next"
import { useDatasetStore } from '@/stores/dataset'
import { Loader2 } from "lucide-vue-next"

const datasetStore = useDatasetStore()
</script>

<template>
  <Stepper class="flex justify-center">
    <StepperItem :step="1">
      <StepperTrigger>
        <StepperIndicator>
            <Loader2 v-if="datasetStore.generationStatus === 'pending'" class="w-4 h-4 animate-spin" />
            <Check v-else-if="datasetStore.generationStatus === 'success'" class="w-4 h-4 text-green-600" />
            <CircleX v-else-if="datasetStore.generationStatus === 'error'" class="w-4 h-4 text-red-600" />
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
            <component :is="Loader" class="w-4 h-4" />
        </StepperIndicator>
        <StepperTitle>Analyze</StepperTitle>
        <StepperDescription>Analyze the generated content</StepperDescription>
      </StepperTrigger>
    </StepperItem>
    <StepperItem :step="3">
      <StepperTrigger>
        <StepperIndicator>
            <component :is="CircleX" class="w-4 h-4 text-red-700" />
        </StepperIndicator>
        <StepperTitle>Clean</StepperTitle>
        <StepperDescription>Clean the generated content</StepperDescription>
      </StepperTrigger>
    </StepperItem>
  </Stepper>
</template>