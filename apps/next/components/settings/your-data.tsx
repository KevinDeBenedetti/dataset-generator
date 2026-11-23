'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Icon } from '@/components/app/icon'
import { deleteMyAccount, ensureFreshSession, errorStatus, exportUrl, logout } from '@/api/sdk'

export function YourData() {
  const t = useTranslations('settings')
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
          action: { label: t('data.signInAgain'), onClick: () => void signInAgain() },
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
          <div className="card-title">{t('data.title')}</div>
          <div className="card-desc">{t('data.description')}</div>
        </div>
      </div>
      <div className="card-foot" style={{ gap: 8 }}>
        <a
          className="btn btn-outline"
          href={exportUrl()}
          onClick={(event) => {
            // A plain link can't renew an expired session: renew it, then go.
            event.preventDefault()
            void ensureFreshSession().finally(() => {
              window.location.href = exportUrl()
            })
          }}
        >
          <Icon name="download" />
          {t('data.export')}
        </a>
        <button
          className="btn btn-outline"
          type="button"
          style={{ color: 'var(--destructive)' }}
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(t('data.confirmDelete'))) remove.mutate()
          }}
        >
          <Icon name="trash" />
          {t('data.delete')}
        </button>
      </div>
    </div>
  )
}
