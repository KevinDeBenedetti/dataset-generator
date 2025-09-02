<script setup lang="ts">
import { ref } from 'vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useDatasetStore } from '@/stores/dataset'

const datasetStore = useDatasetStore()
const url = ref('')
const datasetName = ref('')

const handleGenerate = async () => {
  if (!url.value || !datasetName.value) {
    return
  }
  
  try {
    await datasetStore.generateDataset(url.value, datasetName.value)
  } catch (error) {
    console.error('Erreur lors de la génération:', error)
  }
}

const getStatusIcon = () => {
  switch (datasetStore.generationStatus) {
    case 'pending':
      return '⏳'
    case 'success':
      return '✅'
    case 'error':
      return '❌'
    default:
      return ''
  }
}
</script>

<template>
    <div class="flex flex-col gap-2">
        <Input 
          v-model="url"
          placeholder="URL" 
          :disabled="datasetStore.generationStatus === 'pending'"
        /> 
        <Input 
          v-model="datasetName"
          placeholder="Nom du dataset" 
          :disabled="datasetStore.generationStatus === 'pending'"
        />
        <Button 
          @click="handleGenerate"
          :disabled="!url || !datasetName || datasetStore.generationStatus === 'pending'"
        >
          <span v-if="datasetStore.generationStatus === 'pending'">Génération en cours...</span>
          <span v-else>Générer le Dataset</span>
          <span v-if="getStatusIcon()" class="ml-2">{{ getStatusIcon() }}</span>
        </Button>
        
        <div v-if="datasetStore.generationStatus === 'error'" class="text-red-500 text-sm">
          {{ datasetStore.errorMessage }}
        </div>
        
        <div v-if="datasetStore.generationStatus === 'success'" class="text-green-500 text-sm">
          Dataset généré avec succès !
        </div>
    </div>
</template>