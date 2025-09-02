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
import { Loader, Check, CircleX } from "lucide-vue-next"
</script>

<template>
  <Stepper>
    <StepperItem :step="1">
      <StepperTrigger>
        <StepperIndicator>
            <component :is="Check" class="w-4 h-4 text-green-500" />
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