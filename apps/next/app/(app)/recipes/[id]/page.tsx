'use client'

import { useParams } from 'next/navigation'
import { RecipeEditor } from '@/components/recipes/recipe-editor'

// One recipe: its steps and a live preview, then a run to review.
export default function RecipePage() {
  const params = useParams<{ id: string }>()
  return <RecipeEditor key={params.id} recipeId={params.id} />
}
