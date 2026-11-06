import type { CommercialPursuit, PursuitStage } from '../../api/client'

export const FLOW_STAGES: PursuitStage[] = ['New', 'Contacted', 'Engaged', 'Proposal', 'Won']
export const isClosed = (stage: PursuitStage) => stage === 'Won' || stage === 'Lost'

/** Power need exactly as the API reports it; unknown is never zero. */
export function powerNeed(value: string | null | undefined) {
  const text = value?.trim()
  if (!text) return 'Unknown'
  return /^[\d.,]+$/.test(text) ? `${text} MW` : text
}
export const powerTiming = (value: string | null | undefined) => value?.trim() || 'Unknown'

export function formatDay(value: string | null | undefined) {
  if (!value) return 'Unknown'
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return value
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}
export function formatDateTime(value: string | null | undefined) {
  if (!value) return 'Unknown'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** tel: href only from a plausible phone number; digits and a leading + are the only characters kept. */
export function telHref(value: string | null | undefined) {
  const text = value?.trim()
  if (!text || !/^[+()\d][\d\s().+-]{5,}$/.test(text)) return null
  const digits = text.replace(/[^+\d]/g, '').replace(/(?!^)\+/g, '')
  return (digits.match(/\d/g)?.length ?? 0) >= 7 ? `tel:${digits}` : null
}
export function mailHref(value: string | null | undefined) {
  const text = value?.trim()
  return text && /^[^\s@<>"',;?&=]+@[^\s@<>"',;?&=.]+(?:\.[^\s@<>"',;?&=.]+)+$/.test(text) ? `mailto:${text}` : null
}

export function contactLine(item: CommercialPursuit) {
  const contact = item.contact
  if (contact && (contact.name || contact.company)) return contact.name || contact.company || ''
  if (contact && (contact.phone || contact.email)) return 'Contact available'
  return item.contact_status === 'unknown' ? 'Contact status unavailable' : 'No usable contact method'
}
