<script setup lang="ts">
import { computed, ref } from 'vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Loader2 } from 'lucide-vue-next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'

import { useGenerateStore } from '@/stores/generate'
import { useDatasetStore } from '@/stores/dataset'

const generateStore = useGenerateStore()
const datasetStore = useDatasetStore()
const url = ref('')
const datasetName = ref('')

const targetLanguage = ref<string | null>('fr')
const similarityThreshold = ref([0.9])

const availableLanguages = [
  { value: 'fr', label: 'French' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Spanish' },
  { value: 'de', label: 'German' },
]

const handleGenerate = async () => {
  if (!url.value || !datasetName.value) {
    return
  }

  try {
    await generateStore.generateDataset(url.value, datasetName.value, {
      targetLanguage: targetLanguage.value,
      similarityThreshold: similarityThreshold.value[0],
    })
  } catch (error) {
    console.error('Error during generation:', error)
  }
}

const handleAnalyze = async () => {
  if (!generateStore.dataset?.id) {
    console.error('No dataset ID available for analysis')
    return
  }

  try {
    // Utiliser l'ID du dataset généré pour l'analyse
    await datasetStore.analyzeDataset(generateStore.dataset.id)
  } catch (error) {
    console.error('Error during analysis:', error)
  }
}

const handleClean = async () => {
  if (!generateStore.dataset?.id) {
    console.error('No dataset ID available for cleaning')
    return
  }

  try {
    // Utiliser l'ID du dataset généré pour le nettoyage
    await datasetStore.cleanDataset(generateStore.dataset.id)
  } catch (error) {
    console.error('Error during cleaning:', error)
  }
}

const isAnyProcessing = computed(
  () =>
    generateStore.generationStatus === 'pending' ||
    generateStore.analyzeStatus === 'pending' ||
    generateStore.cleanStatus === 'pending'
)
</script>

<template>
  <div class="w-full flex flex-col gap-6">
    <div class="flex flex-col gap-2">
      <Input v-model="url" placeholder="URL" :disabled="isAnyProcessing" />
      <Input v-model="datasetName" placeholder="Dataset Name" :disabled="isAnyProcessing" />

      <!-- Advanced options -->
      <div class="bg-gray-50 p-3 rounded-lg mt-2">
        <h4 class="text-sm font-medium mb-2">Advanced options</h4>

        <div class="space-y-3">
          <div class="flex flex-col gap-1">
            <label class="text-xs text-gray-500">Target Language</label>
            <Select v-model="targetLanguage">
              <SelectTrigger class="w-full">
                <SelectValue placeholder="Select a language" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="lang in availableLanguages"
                  :key="lang.value"
                  :value="lang.value"
                >
                  {{ lang.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div class="flex flex-col gap-1">
            <div class="flex justify-between">
              <label class="text-xs text-gray-500">Similarity Threshold</label>
              <!-- Fix: show the first value of the array -->
              <span class="text-xs">{{ similarityThreshold[0] }}</span>
            </div>
            <!-- Fix: the slider expects an array -->
            <Slider v-model="similarityThreshold" :min="0.1" :max="1" :step="0.05" />
          </div>
        </div>
      </div>

      <div class="flex gap-2 mt-2">
        <Button
          :disabled="!url || !datasetName || isAnyProcessing"
          class="flex-1"
          @click="handleGenerate"
        >
          <Loader2
            v-if="generateStore.generationStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Generate Dataset</span>
        </Button>

        <Button
          v-if="generateStore.generationStatus === 'success'"
          :disabled="isAnyProcessing"
          variant="outline"
          class="flex-1"
          @click="handleAnalyze"
        >
          <Loader2
            v-if="generateStore.analyzeStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Analyze</span>
        </Button>

        <Button
          v-if="generateStore.analyzeStatus === 'success'"
          :disabled="isAnyProcessing"
          variant="outline"
          class="flex-1"
          @click="handleClean"
        >
          <Loader2
            v-if="generateStore.cleanStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Clean</span>
        </Button>
      </div>

      <div
        v-if="
          generateStore.generationStatus === 'error' ||
          generateStore.analyzeStatus === 'error' ||
          generateStore.cleanStatus === 'error'
        "
        class="text-red-500 text-sm"
      >
        {{ generateStore.errorMessage }}
      </div>
    </div>
  </div>
</template>
