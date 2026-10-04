'use client'

import { useState } from 'react'
import { useFormik } from 'formik'
import { usePathname } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { signOut } from '@components/Contexts/AuthContext'
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
  emptyMkaProfile,
  getMyMkaProfile,
  MkaProfileError,
  putMyMkaProfile,
  validateMkaProfile,
  type MkaProfileValues,
} from '@services/mka/profile'

const QUERY_KEY = 'mka-profile-me'
const GENERIC_ERROR = 'Something went wrong. Please try again.'

/**
 * Non-dismissible gate for signed-in users who have no MKA profile yet
 * (Google sign-in, accounts created before the profile existed).
 * Renders nothing while loading, on error, or once the profile is complete.
 */
export default function MkaProfileGate() {
  const session = useLHSession()
  const pathname = usePathname()
  const queryClient = useQueryClient()
  const token = session?.data?.tokens?.access_token
  const [submitError, setSubmitError] = useState('')

  const { data } = useQuery({
    queryKey: [QUERY_KEY, token],
    queryFn: () => getMyMkaProfile(token as string),
    enabled: !!token,
    staleTime: 60_000,
    retry: 1,
  })

  const formik = useFormik<{ mka_profile: MkaProfileValues }>({
    initialValues: { mka_profile: { ...emptyMkaProfile } },
    validate: (v) => {
      const errs = validateMkaProfile(v.mka_profile)
      return Object.keys(errs).length ? { mka_profile: errs } : {}
    },
    onSubmit: async (v, { setFieldError }) => {
      setSubmitError('')
      try {
        await putMyMkaProfile(v.mka_profile, token as string)
        await queryClient.invalidateQueries({ queryKey: [QUERY_KEY] })
      } catch (e) {
        if (e instanceof MkaProfileError && Object.keys(e.fields).length > 0) {
          for (const [k, msg] of Object.entries(e.fields)) {
            setFieldError(`mka_profile.${k}`, msg)
          }
        } else {
          setSubmitError(e instanceof MkaProfileError ? e.message : GENERIC_ERROR)
        }
      }
    },
  })

  if (!token || pathname?.startsWith('/auth') || !data || data.complete) return null

  return (
    <Dialog open>
      <DialogContent
        className="bg-background text-foreground border-border [&>button:last-child]:hidden sm:max-w-md"
        // dialog.tsx spreads {...props} AFTER its own style, so a style prop replaces
        // it wholesale: the centering/animation props must be repeated here.
        style={{
          zIndex: 'calc(var(--z-popover) - 10)',
          translate: '-50% -50%',
          willChange: 'scale, opacity',
          backfaceVisibility: 'hidden',
          WebkitBackfaceVisibility: 'hidden',
        }}
        onInteractOutside={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <DialogHeader className="p-6 pb-2">
          <DialogTitle className="text-foreground">Complete your profile</DialogTitle>
          <DialogDescription className="text-muted-foreground">
            Tell us your Majlis so we can place you in the right Region. This takes a few seconds.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={formik.handleSubmit} className="space-y-4 p-6 pt-2" noValidate>
          <MkaProfileFields
            idPrefix="gate"
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
          <div className="flex items-center justify-between gap-2">
            <Button type="button" variant="ghost" onClick={() => signOut({ callbackUrl: '/' })}>
              Sign out
            </Button>
            <Button type="submit" disabled={formik.isSubmitting}>
              {formik.isSubmitting ? 'Saving…' : 'Save and continue'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
