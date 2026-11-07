'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import { deleteMyAccount, errorStatus, exportUrl, logout } from '@/api/sdk'

export function YourData() {
  const router = useRouter()
  const queryClient = useQueryClient()
  // Deleting the account takes a sign-in from the last few minutes (a stolen
  // session is not enough): on a 403, offer to sign in again and come back.
  const signInAgain = async () => {
    await logout().catch(() => undefined)
    queryClient.clear()
    router.replace('/login?from=/settings')
  }
  const remove = useMutation({
    mutationFn: deleteMyAccount,
    onSuccess: () => {
      queryClient.clear()
      router.replace('/login')
    },
    onError: (e: Error) => {
      if (errorStatus(e) === 403) {
        toast.error(e.message, {
          action: { label: 'Sign in again', onClick: () => void signInAgain() },
        })
        return
      }
      toast.error(e.message)
    },
  })

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">Your data</div>
          <div className="card-desc">
            Download everything you own (datasets, settings — never your keys), or delete your
            account. Hugging Face repos you published are yours and are not touched. Deleting asks
            you to have signed in within the last 10 minutes.
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
