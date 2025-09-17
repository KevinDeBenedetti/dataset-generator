<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { toast } from 'vue-sonner'
import type { DatasetResponse } from '@/api'

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
import DataGenerateAnalyze from '@/components/dataset/DatasetGenerateAnalyse.vue'
import DataGenerateClean from '@/components/dataset/DatasetGenerateClean.vue'

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

const { dataset, datasets, analyzeStatus, cleanStatus } = storeToRefs(datasetStore)

const selectedDatasetId = ref<string | null>(null)

// Simplified: single watch to sync select <-> input
watch([selectedDatasetId, datasetName], ([newId, newName]) => {
  if (newId) {
    const byId = datasets.value.find((d: DatasetResponse) => d.id === newId)
    if (byId) datasetName.value = byId.name
    return
  }

  // if no id selected, try to find by name and set id, otherwise clear selection
  const byName = datasets.value.find((d: DatasetResponse) => d.name === newName)
  selectedDatasetId.value = byName ? byName.id : null
})

// Show analyze/clean when an existing dataset is selected or when the entered name matches one
const showActions = computed(() => {
  return (
    selectedDatasetId.value !== null ||
    datasets.value.some((d: DatasetResponse) => d.name === datasetName.value) ||
    !!dataset.value
  )
})

const handleGenerate = async () => {
  if (!url.value || !datasetName.value) {
    return
  }

  try {
    await generateStore.generateDataset(url.value, datasetName.value, {
      targetLanguage: targetLanguage.value,
      similarityThreshold: similarityThreshold.value[0] ?? 0.9,
    })

    // Only call analyze/clean with a definite string id: prefer selectedDatasetId, fall back to dataset.value.id
    const id = selectedDatasetId.value ?? dataset.value?.id
    if (id) {
      await datasetStore.analyzeDataset(id)
      toast.success('Dataset analyzed successfully!')
      await datasetStore.cleanDataset(id)
      toast.success('Dataset cleaned successfully!')
    }
  } catch (error) {
    toast.error('Error during dataset generation')
    toast.error(error instanceof Error ? error.message : String(error))
  }
}

const isAnyProcessing = computed(
  () =>
    generateStore.generationStatus === 'pending' ||
    analyzeStatus.value === 'pending' ||
    cleanStatus.value === 'pending'
)

// watch(datasets, (newVal) => {
//   toast.success('Datasets changed:')
//   toast.success(newVal)
// })
</script>

<template>
  <div class="w-full flex flex-col gap-6">
    <div class="flex flex-col gap-2">
      <!-- Select for existing dataset -->
      <Select v-model="selectedDatasetId" class="mb-2" :disabled="isAnyProcessing">
        <SelectTrigger class="w-full">
          <SelectValue placeholder="Select an existing dataset" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="d in datasets" :key="d.id" :value="d.id">
            {{ d.name }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Input v-model="datasetName" placeholder="Dataset name" :disabled="isAnyProcessing" />

      <Input v-model="url" placeholder="URL" :disabled="isAnyProcessing" />

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

        <DataGenerateAnalyze v-if="showActions" />

        <DataGenerateClean v-if="showActions" />
      </div>

      <div
        v-if="
          generateStore.generationStatus === 'error' ||
          analyzeStatus === 'error' ||
          cleanStatus === 'error'
        "
        class="text-red-500 text-sm"
      >
        {{ generateStore.error }}
      </div>
    </div>
  </div>
</template>
