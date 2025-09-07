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

import DatasetResults from './DatasetResults.vue'

const generateStore = useGenerateStore()
const datasetStore = useDatasetStore()
const url = ref('')
const datasetName = ref('')
const dataset = computed(() => generateStore.dataset)

// New options added according to the DatasetGenerationRequest schema
const modelCleaning = ref<string | null>(null)
const targetLanguage = ref<string | null>('fr')
const modelQa = ref<string | null>(null)
// Fix: the slider expects an array
const similarityThreshold = ref([0.9])

const availableModels = [
  { value: 'mistral-small-3.1-24b-instruct-2503', label: 'Mistral Small 3.1' },
  { value: 'mistral-medium-3.1-32b-instruct-2503', label: 'Mistral Medium 3.1' },
  { value: 'mistral-large-3.1-64b-instruct-2503', label: 'Mistral Large 3.1' },
]

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
      modelCleaning: modelCleaning.value,
      targetLanguage: targetLanguage.value,
      modelQa: modelQa.value,
      // Fix: pass the numeric value
      similarityThreshold: similarityThreshold.value[0],
    })

    await handleAnalyze()
    await handleClean()
  } catch (error) {
    console.error('Error during generation:', error)
  }
}

const handleAnalyze = async () => {
  try {
    await generateStore.analyzeDataset()
  } catch (error) {
    console.error('Error during analysis:', error)
  }
}

const handleClean = async () => {
  try {
    await generateStore.cleanDataset()
  } catch (error) {
    console.error('Error during cleaning:', error)
  }
}

const isAnyProcessing = computed(
  () =>
    generateStore.generationStatus === 'pending' ||
    generateStore.analyzeStatus === 'pending' ||
    generateStore.cleanStatus === 'pending',
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
            <label class="text-xs text-gray-500">QA Model</label>
            <Select v-model="modelQa">
              <SelectTrigger class="w-full">
                <SelectValue placeholder="Select a model" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="model in availableModels"
                  :key="model.value"
                  :value="model.value"
                >
                  {{ model.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-xs text-gray-500">Cleaning Model</label>
            <Select v-model="modelCleaning">
              <SelectTrigger class="w-full">
                <SelectValue placeholder="Select a model" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="model in availableModels"
                  :key="model.value"
                  :value="model.value"
                >
                  {{ model.label }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

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
          @click="handleGenerate"
          :disabled="!url || !datasetName || isAnyProcessing"
          class="flex-1"
        >
          <Loader2
            v-if="generateStore.generationStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Generate Dataset</span>
        </Button>

        <Button
          v-if="generateStore.generationStatus === 'success'"
          @click="handleAnalyze"
          :disabled="isAnyProcessing"
          variant="outline"
          class="flex-1"
        >
          <Loader2
            v-if="generateStore.analyzeStatus === 'pending'"
            class="w-4 h-4 mr-2 animate-spin"
          />
          <span v-else>Analyze</span>
        </Button>

        <Button
          v-if="generateStore.analyzeStatus === 'success'"
          @click="handleClean"
          :disabled="isAnyProcessing"
          variant="outline"
          class="flex-1"
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

    <!-- Generated dataset display -->
    <div v-if="generateStore.generationStatus === 'success' && dataset">
      <h3 class="text-lg font-semibold mb-2">Generated Dataset</h3>
      <DatasetResults :result="dataset" />
    </div>

    <!-- Similarity analysis display -->
    <div v-if="generateStore.analyzeStatus === 'success' && datasetStore.state.analyzingResult">
      <h3 class="text-lg font-semibold mb-2">Similarity Analysis</h3>
      <div class="bg-gray-50 p-4 rounded-lg">
        <p><strong>Dataset:</strong> {{ datasetStore.state.analyzingResult.dataset }}</p>
        <p>
          <strong>Total records:</strong> {{ datasetStore.state.analyzingResult.total_records }}
        </p>
        <p>
          <strong>Similar pairs found:</strong>
          {{ datasetStore.state.analyzingResult.similar_pairs_found }}
        </p>
        <p><strong>Threshold:</strong> {{ datasetStore.state.analyzingResult.threshold }}</p>
      </div>
    </div>

    <!-- Cleaning results display -->
    <div v-if="generateStore.cleanStatus === 'success' && datasetStore.state.cleaningResult">
      <h3 class="text-lg font-semibold mb-2">Cleaning completed</h3>
      <div class="bg-green-50 p-4 rounded-lg">
        <p><strong>Dataset:</strong> {{ datasetStore.state.cleaningResult.dataset }}</p>
        <p><strong>Total records:</strong> {{ datasetStore.state.cleaningResult.total_records }}</p>
        <p>
          <strong>Removed records:</strong>
          {{ datasetStore.state.cleaningResult.removed_records }}
        </p>
        <p><strong>Threshold:</strong> {{ datasetStore.state.cleaningResult.threshold }}</p>
      </div>
    </div>
  </div>
</template>
