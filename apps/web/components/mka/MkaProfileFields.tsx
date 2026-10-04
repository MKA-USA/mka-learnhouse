'use client'

import { useQuery } from '@tanstack/react-query'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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

const NONE = '__none__' // Radix Select forbids empty-string item values

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
          disabled={disabled || !options}
        />
        {region && <p className="text-xs text-muted-foreground">Region: {region}</p>}
        {isError && (
          <p className="text-xs text-destructive">Couldn&apos;t load Majlis list. Refresh to retry.</p>
        )}
        {errors.majlis && <p className="text-xs text-destructive">{errors.majlis}</p>}
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
          onChange={(e) => onChange('mobile', e.target.value)}
        />
        {errors.mobile && <p className="text-xs text-destructive">{errors.mobile}</p>}
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
          onChange={(e) => onChange('amc_id', e.target.value)}
        />
        {errors.amc_id && <p className="text-xs text-destructive">{errors.amc_id}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-tanzeem`}>Tanzeem (optional)</Label>
        <Select
          value={values.tanzeem || NONE}
          onValueChange={(v) => onChange('tanzeem', v === NONE ? '' : v)}
          disabled={disabled}
        >
          <SelectTrigger id={`${idPrefix}-tanzeem`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>Not specified</SelectItem>
            {(options?.tanzeem ?? []).map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.tanzeem && <p className="text-xs text-destructive">{errors.tanzeem}</p>}
      </div>
    </div>
  )
}
