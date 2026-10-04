'use client'

import { useState } from 'react'
import { useFormik } from 'formik'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import MkaProfileFields from './MkaProfileFields'
import {
  applyMkaServerErrors,
  getMemberMkaProfile,
  MkaProfileError,
  profileToValues,
  putMemberMkaProfile,
  validateMkaProfile,
  type MkaProfileStatus,
  type MkaProfileValues,
} from '@services/mka/profile'

const QUERY_KEY = 'mka-profile-member'
const GENERIC_ERROR = 'Something went wrong. Please try again.'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  userId: number | string
  orgId: number | string
  displayName: string
  onSaved?: () => void
}

/**
 * Admin dialog (opened from the org Users table) to edit a member's MKA profile.
 * PUT is a FULL REPLACE, so the form always starts from the member's current
 * profile and sends the complete object. Rendered only while `open`.
 */
export default function MkaProfileEditDialog({
  open,
  onOpenChange,
  userId,
  orgId,
  displayName,
  onSaved,
}: Props) {
  const session = useLHSession()
  const token = session?.data?.tokens?.access_token

  const { data, isPending, error } = useQuery({
    queryKey: [QUERY_KEY, orgId, userId, token],
    queryFn: () => getMemberMkaProfile(userId, orgId, token as string),
    enabled: open && !!token,
    staleTime: 0,
    retry: false,
  })

  if (!open) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-background text-foreground border-border sm:max-w-md">
        <DialogHeader className="p-6 pb-2">
          <DialogTitle className="text-foreground">Edit profile</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            {displayName}
            {data && !data.complete ? ' — No profile yet' : ''}
          </DialogDescription>
        </DialogHeader>
        {isPending || !token ? (
          <p className="p-6 pt-2 text-sm text-muted-foreground" role="status">
            Loading profile…
          </p>
        ) : error ? (
          <p className="p-6 pt-2 text-sm text-destructive" role="alert">
            {error instanceof MkaProfileError ? error.message : GENERIC_ERROR}
          </p>
        ) : (
          <EditForm
            initial={data}
            userId={userId}
            orgId={orgId}
            token={token}
            onCancel={() => onOpenChange(false)}
            onSaved={() => {
              onSaved?.()
              onOpenChange(false)
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function EditForm({
  initial,
  userId,
  orgId,
  token,
  onCancel,
  onSaved,
}: {
  initial: MkaProfileStatus
  userId: number | string
  orgId: number | string
  token: string
  onCancel: () => void
  onSaved: () => void
}) {
  const queryClient = useQueryClient()
  const [submitError, setSubmitError] = useState('')

  const formik = useFormik<{ mka_profile: MkaProfileValues }>({
    initialValues: { mka_profile: profileToValues(initial) },
    validate: (v) => {
      const errs = validateMkaProfile(v.mka_profile)
      return Object.keys(errs).length ? { mka_profile: errs } : {}
    },
    onSubmit: async (v, { setFieldError }) => {
      setSubmitError('')
      try {
        await putMemberMkaProfile(userId, orgId, v.mka_profile, token)
      } catch (e) {
        if (e instanceof MkaProfileError) {
          const pinned = applyMkaServerErrors(e.status, formDetail(e), setFieldError)
          if (!pinned) setSubmitError(e.message)
        } else {
          setSubmitError(GENERIC_ERROR)
        }
        return
      }
      toast.success('Profile saved')
      await queryClient.invalidateQueries({ queryKey: [QUERY_KEY] })
      onSaved()
    },
  })

  return (
    <form onSubmit={formik.handleSubmit} className="space-y-4 p-6 pt-2" noValidate>
      <MkaProfileFields
        idPrefix="admin-edit"
        values={formik.values.mka_profile}
        errors={formik.submitCount > 0 ? formik.errors.mka_profile : {}}
        disabled={formik.isSubmitting}
        onChange={(field, value) => formik.setFieldValue(`mka_profile.${field}`, value)}
      />
      {submitError && (
        <p className="text-sm text-destructive" role="alert">
          {submitError}
        </p>
      )}
      <div className="flex items-center justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={formik.isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" disabled={formik.isSubmitting}>
          {formik.isSubmitting ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </form>
  )
}

/** Rebuild the backend `detail` shape from an already-parsed MkaProfileError. */
function formDetail(e: MkaProfileError): unknown {
  return Object.entries(e.fields).map(([field, message]) => ({ field, message }))
}
