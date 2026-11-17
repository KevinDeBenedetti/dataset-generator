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

/** What to save for the picker's state: null removes the schedule. */
export function toSchedule(form: ScheduleForm): ScheduleTiming | null {
  if (!form.every) return null
  // "HH:MM" within a day, or the default: an empty field must not read as midnight.
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(form.time)
  return {
    every: form.every,
    at_hour: match ? Number(match[1]) : 3,
    at_minute: match ? Number(match[2]) : 0,
    publish: form.publish,
  }
}
