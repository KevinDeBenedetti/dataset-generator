'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import { deleteMyAccount, exportUrl } from '@/api/sdk'

export function YourData() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: deleteMyAccount,
    onSuccess: () => {
      queryClient.clear()
      router.replace('/login')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Your data</div>
          <div className="card-desc">
            Download everything you own (datasets, settings — never your keys), or delete your
            account. Hugging Face repos you published are yours and are not touched.
          </div>
        </div>
      </div>
      <div className="card-foot" style={{ gap: 8 }}>
        <a className="btn btn-outline" href={exportUrl()}>
          <Icon name="download" />
          Export my data
        </a>
        <button
          className="btn btn-outline"
          type="button"
          style={{ color: 'var(--destructive)' }}
          disabled={remove.isPending}
          onClick={() => {
            if (
              window.confirm(
                'Delete your account, your datasets, your runs and your saved keys? This cannot be undone.',
              )
            ) {
              remove.mutate()
            }
          }}
        >
          <Icon name="trash" />
          Delete my account
        </button>
      </div>
    </div>
  )
}
