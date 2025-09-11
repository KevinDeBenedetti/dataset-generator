<script setup lang="ts">
import { useDatasetStore } from '@/stores/dataset'
import { useLangfuseStore } from '@/stores/langfuse'
import { TableCell, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'

interface Dataset {
  id: string
  name: string
  description: string
}

interface Props {
  dataset: Dataset
}

const props = defineProps<Props>()
const datasetStore = useDatasetStore()
const langfuseStore = useLangfuseStore()

const truncateText = (text: string, maxLength: number) => {
  return text.length > maxLength ? text.substring(0, maxLength) + '…' : text
}

const handleDeleteDataset = async () => {
  if (confirm(`Are you sure you want to delete the dataset "${props.dataset.name}"?`)) {
    try {
      await datasetStore.deleteDataset(props.dataset.id)
      toast.success('Dataset deleted successfully!')
    } catch (error) {
      console.error('Error during deletion:', error)
      toast.error('Failed to delete dataset.')
    }
  }
}

const handleExportDataset = async () => {
  try {
    await langfuseStore.exportToLangfuse(props.dataset.name)
    toast.success('Dataset exported successfully!')
  } catch (error) {
    console.error('Error during export:', error)
    toast.error('Failed to export dataset.')
  }
}
</script>

<template>
  <TableRow>
    <TableCell class="font-mono text-sm text-gray-500">
      {{ truncateText(dataset.id, 8) }}
    </TableCell>
    <TableCell class="font-medium">
      {{ dataset.name }}
    </TableCell>
    <TableCell class="text-sm text-gray-600">
      {{ truncateText(dataset.description, 20) }}
    </TableCell>
    <TableCell class="text-center">
      <div class="flex gap-2 justify-center">
        <RouterLink :to="`/datasets/${dataset.id}`">
          <Button variant="outline" size="sm" class="text-blue-600 hover:text-blue-700">
            Open
          </Button>
        </RouterLink>
        <Button
          @click="handleDeleteDataset"
          variant="outline"
          size="sm"
          class="text-red-600 hover:text-red-700"
        >
          Delete
        </Button>
      </div>
    </TableCell>
    <TableCell class="font-medium">
      <Button
        @click="handleExportDataset"
        variant="outline"
        size="sm"
        class="text-gray-600 hover:text-gray-700 w-full"
      >
        Export
      </Button>
    </TableCell>
  </TableRow>
</template>
