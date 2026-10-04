'use client'

import * as React from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { MkaOptions } from '@services/mka/profile'

type Props = {
  value: string
  onChange: (name: string) => void
  options: MkaOptions['majlis']
  id?: string
  invalid?: boolean
  disabled?: boolean
  contentClassName?: string
  contentStyle?: React.CSSProperties
}

export default function MajlisCombobox({
  value,
  onChange,
  options,
  id,
  invalid,
  disabled,
  contentClassName,
  contentStyle,
}: Props) {
  const [open, setOpen] = React.useState(false)

  const groups = React.useMemo(() => {
    const byRegion = new Map<string, MkaOptions['majlis']>()
    for (const o of options) {
      byRegion.set(o.region, [...(byRegion.get(o.region) ?? []), o])
    }
    return Array.from(byRegion.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [options])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-invalid={invalid || undefined}
          disabled={disabled}
          className={cn(
            'w-full justify-between font-normal',
            !value && 'text-muted-foreground',
            invalid && 'border-destructive'
          )}
        >
          {value || 'Select your Majlis'}
          <ChevronsUpDown className="ms-2 size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className={cn('w-(--radix-popover-trigger-width) p-0', contentClassName)}
        style={contentStyle}
        align="start"
      >
        <Command>
          <CommandInput placeholder="Search Majlis or Region…" />
          <CommandList>
            <CommandEmpty>No Majlis found.</CommandEmpty>
            {groups.map(([region, items]) => (
              <CommandGroup key={region} heading={region}>
                {items.map((m) => (
                  <CommandItem
                    key={m.name}
                    value={`${m.name} ${m.region}`}
                    onSelect={() => {
                      onChange(m.name)
                      setOpen(false)
                    }}
                  >
                    <Check
                      className={cn('me-2 size-4', value === m.name ? 'opacity-100' : 'opacity-0')}
                    />
                    {m.name}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
