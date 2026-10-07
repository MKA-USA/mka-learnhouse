'use client'

import { useQuery } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import MajlisCombobox from './MajlisCombobox'
import {
  getMkaOptions,
  type MkaProfileFieldErrors,
  type MkaProfileValues,
} from '@services/mka/profile'

type Props = {
  values: MkaProfileValues
  errors?: MkaProfileFieldErrors
  onChange: (field: keyof MkaProfileValues, value: string) => void
  disabled?: boolean
  idPrefix?: string
}

const NONE = '__none__' // Radix RadioGroup forbids empty-string item values

export default function MkaProfileFields({
  values,
  errors = {},
  onChange,
  disabled,
  idPrefix = 'mka',
}: Props) {
  const { data: options, isError } = useQuery({
    queryKey: ['mka-profile-options'],
    queryFn: getMkaOptions,
    staleTime: Infinity,
  })
  const region = options?.majlis.find((m) => m.name === values.majlis)?.region
  // aria-describedby target, only while the field's error paragraph is rendered
  const errId = (f: keyof MkaProfileValues) =>
    errors[f] ? `${idPrefix}-${f}-error` : undefined

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-majlis`}>Majlis *</Label>
        <MajlisCombobox
          id={`${idPrefix}-majlis`}
          value={values.majlis}
          onChange={(v) => onChange('majlis', v)}
          options={options?.majlis ?? []}
          invalid={!!errors.majlis}
          aria-describedby={errId('majlis')}
          disabled={disabled || !options}
        />
        {region && <p className="text-xs text-muted-foreground">Region: {region}</p>}
        {isError && (
          <p className="text-xs text-destructive">Couldn&apos;t load Majlis list. Refresh to retry.</p>
        )}
        {errors.majlis && (
          <p id={errId('majlis')} role="alert" className="text-xs text-destructive">
            {errors.majlis}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-mobile`}>Mobile number (optional)</Label>
        <Input
          id={`${idPrefix}-mobile`}
          type="tel"
          inputMode="tel"
          autoComplete="tel-national"
          placeholder="(555) 234-0142"
          value={values.mobile}
          disabled={disabled}
          aria-invalid={!!errors.mobile || undefined}
          aria-describedby={errId('mobile')}
          onChange={(e) => onChange('mobile', e.target.value)}
        />
        {errors.mobile && (
          <p id={errId('mobile')} role="alert" className="text-xs text-destructive">
            {errors.mobile}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-amc`}>AMC ID (optional)</Label>
        <Input
          id={`${idPrefix}-amc`}
          inputMode="numeric"
          autoComplete="off"
          placeholder="Digits only"
          value={values.amc_id}
          disabled={disabled}
          aria-invalid={!!errors.amc_id || undefined}
          aria-describedby={errId('amc_id')}
          onChange={(e) => onChange('amc_id', e.target.value)}
        />
        {errors.amc_id && (
          <p id={errId('amc_id')} role="alert" className="text-xs text-destructive">
            {errors.amc_id}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label id={`${idPrefix}-tanzeem-label`}>Tanzeem (optional)</Label>
        <RadioGroup
          id={`${idPrefix}-tanzeem`}
          value={values.tanzeem || NONE}
          onValueChange={(v) => onChange('tanzeem', v === NONE ? '' : v)}
          disabled={disabled}
          aria-labelledby={`${idPrefix}-tanzeem-label`}
          aria-invalid={!!errors.tanzeem || undefined}
          aria-describedby={errId('tanzeem')}
          className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-x-5"
        >
          {[{ value: NONE, label: 'Not specified' }, ...(options?.tanzeem ?? [])].map((t) => {
            const id = `${idPrefix}-tanzeem-${t.value}`
            return (
              <div key={t.value} className="flex items-center gap-2">
                <RadioGroupItem
                  id={id}
                  value={t.value}
                  aria-invalid={!!errors.tanzeem || undefined}
                />
                <Label htmlFor={id} className="font-normal">
                  {t.label}
                </Label>
              </div>
            )
          })}
        </RadioGroup>
        {errors.tanzeem && (
          <p id={errId('tanzeem')} role="alert" className="text-xs text-destructive">
            {errors.tanzeem}
          </p>
        )}
      </div>
    </div>
  )
}
