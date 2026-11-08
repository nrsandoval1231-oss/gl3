import type { ProjectResult } from '../../api/client'

/** Only export contact routes already permitted by the server projection. */
function permittedMethod(href: string | null | undefined): string | null {
  if (!href || /[\r\n]/.test(href)) return null
  if (/^mailto:[^\s?@]+@[^\s?@]+\.[^\s?@]+$/i.test(href)) return href.slice(7)
  if (/^tel:\+?[0-9(). -]{7,25}$/i.test(href)) return href.slice(4)
  return null
}

export function safeCsvCell(value: string): string {
  const safe = /^[\s\t]*[=+@-]/.test(value) ? `'${value}` : value
  return `"${safe.replaceAll('"', '""')}"`
}

/** A page export preserves the displayed amount class and never invents a residual gap. */
export function projectPageCsv(projects: ProjectResult[], accountName?: string, scope = 'Current page'): string {
  const rows = [['Export scope', 'Account', 'Project', 'Location', 'Power statement', 'Amount class', 'Power statement basis', 'Demand scope', 'Timing', 'Timing meaning', 'Why now', 'Next action', 'Permitted contact methods']]
  for (const project of projects) {
    const assessment = project.shortlist_assessment
    rows.push([scope, accountName ?? project.company ?? '', project.name, project.location ?? '', project.power_summary ?? '', project.power_amount_class ?? 'unknown', project.power_summary_kind ?? 'unknown', assessment?.scope ?? '', project.event?.date ?? '', project.event?.label ?? '', assessment?.why_now ?? '', assessment?.next_step ?? project.next_action ?? '', project.contact.map(contact => permittedMethod(contact.href)).filter(Boolean).join('; ')])
  }
  return rows.map(row => row.map(safeCsvCell).join(',')).join('\r\n')
}

export function downloadProjectPage(projects: ProjectResult[], accountName?: string, scope = 'Current page') {
  const url = URL.createObjectURL(new Blob([projectPageCsv(projects, accountName, scope)], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = 'gridlens-current-page.csv'; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
