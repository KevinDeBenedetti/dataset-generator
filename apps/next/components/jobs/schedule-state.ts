// Pure state of a schedule picker (schedule-picker.tsx): what it shows from a
// saved schedule — a recipe's or a whole-account job's — and what it sends back.

/** The timing every schedule route takes and returns. */
export interface ScheduleTiming {
  every: 'day' | 'week' | 'month'
  at_hour: number
  at_minute: number
  publish: boolean
}

/** A saved schedule, as far as the picker reads it. */
export type SavedSchedule = {
  every?: 'day' | 'week' | 'month' | null
  at_hour?: number
  at_minute?: number
  publish?: boolean
}

export type Every = '' | 'day' | 'week' | 'month'

/** What the schedule picker shows. `every` is '' without a schedule. */
export interface ScheduleForm {
  every: Every
  /** "HH:MM", UTC. */
  time: string
  publish: boolean
}

const pad = (n: number) => String(n).padStart(2, '0')

/** The picker's state for a saved schedule, or for none: off, 03:00, and
 * publishing what passes once it is switched on. */
export function scheduleForm(saved: SavedSchedule | null | undefined): ScheduleForm {
  return {
    every: (saved?.every ?? '') as Every,
    time: `${pad(saved?.at_hour ?? 3)}:${pad(saved?.at_minute ?? 0)}`,
    publish: saved?.publish ?? true,
  }
}

/** "HH:MM" within a day as numbers, else the default, 03:00: an empty or
 * mangled field must not read as midnight. */
export function timeOf(time: string): { at_hour: number; at_minute: number } {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(time)
  return match
    ? { at_hour: Number(match[1]), at_minute: Number(match[2]) }
    : { at_hour: 3, at_minute: 0 }
}

/** What to save for the picker's state: null removes the schedule. */
export function toSchedule(form: ScheduleForm): ScheduleTiming | null {
  if (!form.every) return null
  return { every: form.every, ...timeOf(form.time), publish: form.publish }
}

/** One option's value, compared: no value and null alike, a list whatever
 * its order. */
function comparable(value: unknown): string {
  if (value === undefined || value === null || value === '') return 'null'
  if (Array.isArray(value)) return JSON.stringify(value.map(String).toSorted())
  return JSON.stringify(value)
}

/** Whether a schedule would run with other options or another model than the
 * card shows now. A key one side leaves out counts as its default (null). */
export function differsFromCard(
  saved: { options?: Record<string, unknown>; model_ref?: string | null },
  card: { options: Record<string, unknown>; modelRef: string | null },
): boolean {
  const savedOptions = saved.options ?? {}
  const keys = new Set([...Object.keys(savedOptions), ...Object.keys(card.options)])
  for (const key of keys) {
    if (comparable(savedOptions[key]) !== comparable(card.options[key])) return true
  }
  return comparable(saved.model_ref) !== comparable(card.modelRef)
}

/** Why a schedule's latest time started no run, as its server keeps it. */
export interface ScheduleSkip {
  reason: string
  at: string
}

/** The line a schedule shows when its latest time started no run, or null. */
export function skipNotice(
  skipped: ScheduleSkip | null | undefined,
  when: (at: string) => string = (at) => new Date(at).toLocaleString(),
): string | null {
  if (!skipped?.reason) return null
  const reason = skipped.reason.replace(/[.\s]+$/, '')
  return `The run scheduled for ${when(skipped.at)} did not start: ${reason}. Fix it, then save the schedule again.`
}
