<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useDatasetStore } from '@/stores/dataset'
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'

const datasetStore = useDatasetStore()
const { datasets, loading, error } = storeToRefs(datasetStore)

const handleRetry = () => {
  datasetStore.resetError()
  datasetStore.fetchDatasets()
}

const handleOpenDataset = (datasetId: string, datasetName: string) => {
  // TODO: Implement navigation to dataset detail view
  console.log('Open dataset:', { id: datasetId, name: datasetName })
}

const handleDeleteDataset = async (datasetId: string, datasetName: string) => {
  if (confirm(`Are you sure you want to delete the dataset "${datasetName}"?`)) {
    try {
      await datasetStore.deleteDataset(datasetId)
      // The dataset is automatically removed from the list by the store
    } catch (error) {
      console.error('Error during deletion:', error)
      // The error is already handled by the store
    }
  }
}

onMounted(() => {
  datasetStore.fetchDatasets()
})
</script>

<template>
  <main class="p-4 flex flex-col justify-center">
    <section class="max-w-6xl mx-auto flex flex-col gap-4 w-full">
      <h1 class="mt-6 mb-4 text-3xl font-bold text-center">Datasets</h1>

      <!-- Loading state -->
      <div v-if="loading" class="space-y-3">
        <Skeleton class="h-4 w-full" />
        <Skeleton class="h-4 w-full" />
        <Skeleton class="h-4 w-full" />
      </div>

      <!-- Error state -->
      <div v-else-if="error" class="text-center p-4 text-red-600 bg-red-50 rounded-lg">
        <p>{{ error }}</p>
        <button
          @click="handleRetry"
          class="mt-2 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
        >
          Retry
        </button>
      </div>

      <!-- Datasets table -->
      <div v-else-if="datasets && datasets.length > 0" class="border rounded-lg overflow-x-auto">
        <Table class="w-full">
          <TableCaption> List of {{ datasets.length }} available dataset(s) </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Name</TableHead>
              <TableHead> Description </TableHead>
              <TableHead class="text-center">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="dataset in datasets" :key="dataset.id">
              <TableCell class="font-mono text-sm text-gray-500">
                {{ dataset.id.length > 8 ? dataset.id.substring(0, 8) + '…' : dataset.id }}
              </TableCell>
              <TableCell class="font-medium">
                {{ dataset.name }}
              </TableCell>
              <TableCell class="text-sm text-gray-600">
                {{
                  dataset.description.length > 40
                    ? dataset.description.substring(0, 40) + '…'
                    : dataset.description
                }}
              </TableCell>
              <TableCell class="text-center">
                <div class="flex gap-2 justify-center">
                  <Button
                    @click="handleOpenDataset(dataset.id, dataset.name)"
                    variant="outline"
                    size="sm"
                    class="text-blue-600 hover:text-blue-700"
                  >
                    Open
                  </Button>
                  <Button
                    @click="handleDeleteDataset(dataset.id, dataset.name)"
                    variant="outline"
                    size="sm"
                    class="text-red-600 hover:text-red-700"
                  >
                    Delete
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <!-- Empty state -->
      <div v-else class="text-center p-8 text-gray-500">
        <p class="text-lg">No datasets available</p>
        <p class="text-sm mt-2">Create your first dataset to get started</p>
      </div>
    </section>
  </main>
</template>
