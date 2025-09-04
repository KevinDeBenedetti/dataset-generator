<script setup lang="ts">
import { useDatasetStore } from '@/stores/dataset'
import { TableCell, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'

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

const truncateText = (text: string, maxLength: number) => {
  return text.length > maxLength ? text.substring(0, maxLength) + '…' : text
}

const handleOpenDataset = () => {
  // TODO: Implement navigation to dataset detail view
  console.log('Open dataset:', { id: props.dataset.id, name: props.dataset.name })
}

const handleDeleteDataset = async () => {
  if (confirm(`Are you sure you want to delete the dataset "${props.dataset.name}"?`)) {
    try {
      await datasetStore.deleteDataset(props.dataset.id)
    } catch (error) {
      console.error('Error during deletion:', error)
    }
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
      {{ truncateText(dataset.description, 40) }}
    </TableCell>
    <TableCell class="text-center">
      <div class="flex gap-2 justify-center">
        <Button
          @click="handleOpenDataset"
          variant="outline"
          size="sm"
          class="text-blue-600 hover:text-blue-700"
        >
          Open
        </Button>
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
  </TableRow>
</template>
