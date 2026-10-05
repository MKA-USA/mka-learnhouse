// MKA fork — describeRule with a levels-only fallback until /options has loaded.
import { describeRule } from '../audience/describe'
import type { DescribeOptions } from '../audience/describe'
import type { AudienceOptions, Rule } from '../audience/types'

export const FALLBACK_DESCRIBE: DescribeOptions = {
  levels: [
    { key: 'national', label: 'National' },
    { key: 'regional', label: 'Regional' },
    { key: 'local', label: 'Local' },
  ],
  departments: [],
  roles: [],
  regions: [],
  majlis: [],
}

export const describeWith = (rule: Rule, o: AudienceOptions | undefined): string => describeRule(rule, o ?? FALLBACK_DESCRIBE)

/** Computed label when options are loaded (so renamed departments etc. read correctly); the stored label is only a fallback. */
export const sectionLabel = (rule: Rule, o: AudienceOptions | undefined): string =>
  o ? describeWith(rule, o) : rule.label || describeWith(rule, o)
