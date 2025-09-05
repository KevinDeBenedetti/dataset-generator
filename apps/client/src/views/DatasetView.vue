<script setup lang="ts">
import { onMounted, computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useDatasetStore } from '@/stores/dataset'
import { useRoute, useRouter } from 'vue-router'
import DatasetTable from '@/components/dataset/DatasetTable.vue'
import LoadingState from '@/components/dataset/LoadingState.vue'
import ErrorState from '@/components/dataset/ErrorState.vue'
import EmptyState from '@/components/dataset/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const datasetStore = useDatasetStore()
const { datasets, loading, error } = storeToRefs(datasetStore)

const selectedDataset = ref(null)
const datasetData = ref(null)
const loadingData = ref(false)

const hasDatasets = computed(() => datasets.value && datasets.value.length > 0)
const isViewingDataset = computed(() => selectedDataset.value !== null)

const loadDatasetFromId = async (datasetId) => {
  try {
    loadingData.value = true

    // D'abord, chercher le dataset dans la liste existante
    const datasetFromList = datasets.value.find((d) => d.id === datasetId)

    if (datasetFromList) {
      selectedDataset.value = datasetFromList
    } else {
      // Si la liste des datasets n'est pas chargée, charger tous les datasets
      if (!datasets.value.length) {
        await datasetStore.fetchDatasets()
        const dataset = datasets.value.find((d) => d.id === datasetId)
        if (dataset) {
          selectedDataset.value = dataset
        } else {
          throw new Error('Dataset non trouvé')
        }
      } else {
        throw new Error('Dataset non trouvé')
      }
    }

    // Charger les données du dataset
    datasetData.value = await datasetStore.fetchDatasetData(datasetId)
  } catch (err) {
    console.error('Erreur lors du chargement des données:', err)
  } finally {
    loadingData.value = false
  }
}

const handleBackToList = () => {
  router.push('/datasets')
}

// Surveiller les changements de route
watch(
  () => route.params.id,
  (newId) => {
    if (newId) {
      loadDatasetFromId(newId)
    } else {
      selectedDataset.value = null
      datasetData.value = null
    }
  },
  { immediate: true },
)

onMounted(async () => {
  // Si on a un ID dans l'URL, charger le dataset correspondant
  if (route.params.id) {
    await loadDatasetFromId(route.params.id)
  } else {
    // Sinon, charger la liste des datasets
    await datasetStore.fetchDatasets()
  }
})
</script>

<template>
  <section class="max-w-2xl mx-auto flex flex-col gap-4 w-full">
    <h1 class="mt-6 mb-4 text-3xl font-bold text-center">
      {{ isViewingDataset ? selectedDataset.name : 'Datasets' }}
    </h1>

    <!-- Bouton de retour quand on visualise un dataset -->
    <button
      v-if="isViewingDataset"
      @click="handleBackToList"
      class="self-start px-4 py-2 bg-gray-500 text-white rounded hover:bg-gray-600"
    >
      ← Retour à la liste
    </button>

    <!-- États de chargement et d'erreur -->
    <LoadingState v-if="loading || loadingData" />
    <ErrorState v-else-if="error" />

    <!-- Vue des données du dataset -->
    <div v-else-if="isViewingDataset && datasetData" class="bg-white rounded-lg shadow p-6">
      <div class="mb-4">
        <h2 class="text-xl font-semibold mb-2">{{ selectedDataset.name }}</h2>
        <p class="text-gray-600">{{ selectedDataset.description }}</p>
      </div>

      <!-- Affichage des données - adaptez selon votre structure de données -->
      <div class="overflow-x-auto">
        <table class="min-w-full border-collapse border border-gray-300">
          <thead>
            <tr class="bg-gray-50">
              <th
                v-for="(value, key) in datasetData[0]"
                :key="key"
                class="border border-gray-300 px-4 py-2 text-left"
              >
                {{ key }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in datasetData" :key="index">
              <td v-for="(value, key) in row" :key="key" class="border border-gray-300 px-4 py-2">
                {{ value }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Liste des datasets -->
    <DatasetTable v-else-if="hasDatasets" :datasets="datasets" />
    <EmptyState v-else />
  </section>
</template>
