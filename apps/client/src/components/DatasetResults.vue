<script setup lang="ts">
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'

interface QAPair {
  question: string
  answer: string
  context: string
  confidence: number
}

interface DatasetResult {
  qa_pairs: QAPair[]
  new_pairs: number
  exact_duplicates_skipped: number
  similar_duplicates_skipped: number
  similarity_threshold: number
}

defineProps<{
  result: DatasetResult
}>()
</script>

<template>
  <div class="space-y-6">
    <!-- Statistiques générales -->
    <Card>
      <CardHeader>
        <CardTitle>Résumé de génération</CardTitle>
        <CardDescription>Statistiques du dataset généré</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="text-center">
            <div class="text-2xl font-bold text-green-600">{{ result.new_pairs }}</div>
            <div class="text-sm text-muted-foreground">Nouvelles paires</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold text-orange-600">
              {{ result.exact_duplicates_skipped }}
            </div>
            <div class="text-sm text-muted-foreground">Doublons exacts</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold text-blue-600">
              {{ result.similar_duplicates_skipped }}
            </div>
            <div class="text-sm text-muted-foreground">Doublons similaires</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold">{{ result.similarity_threshold }}</div>
            <div class="text-sm text-muted-foreground">Seuil de similarité</div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- Liste des paires Q&R -->
    <Card>
      <CardHeader>
        <CardTitle>Paires Questions-Réponses ({{ result.qa_pairs.length }})</CardTitle>
        <CardDescription>Dataset généré avec contexte et niveau de confiance</CardDescription>
      </CardHeader>
      <CardContent>
        <ScrollArea class="h-[600px]">
          <div class="space-y-4">
            <div
              v-for="(pair, index) in result.qa_pairs"
              :key="index"
              class="border rounded-lg p-4 space-y-3"
            >
              <!-- En-tête avec index et confiance -->
              <div class="flex items-center justify-between">
                <Badge variant="outline">Paire {{ index + 1 }}</Badge>
                <Badge
                  :variant="pair.confidence === 1 ? 'default' : 'secondary'"
                  class="flex items-center gap-1"
                >
                  <span class="text-xs">⭐</span>
                  {{ pair.confidence }}
                </Badge>
              </div>

              <!-- Question -->
              <div>
                <h4 class="font-semibold text-blue-700 mb-2">❓ Question</h4>
                <p class="text-sm">{{ pair.question }}</p>
              </div>

              <Separator />

              <!-- Réponse -->
              <div>
                <h4 class="font-semibold text-green-700 mb-2">✅ Réponse</h4>
                <p class="text-sm">{{ pair.answer }}</p>
              </div>

              <Separator />

              <!-- Contexte -->
              <div>
                <h4 class="font-semibold text-gray-700 mb-2">📄 Contexte</h4>
                <p class="text-xs text-muted-foreground italic bg-gray-50 p-2 rounded">
                  {{ pair.context }}
                </p>
              </div>
            </div>
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  </div>
</template>
