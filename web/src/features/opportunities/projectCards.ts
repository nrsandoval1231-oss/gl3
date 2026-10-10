import type { Opportunity } from '../../api/client'

export type ProjectCard = {
  key: string
  title: string
  members: Opportunity[]
  grouped: boolean
  groupTotal?: number
  complete?: boolean
}

export type SignalDisplayDecision = 'SHOW' | 'REVIEW' | 'HOLD'

export function signalDisplayDecision(members: Opportunity[]): SignalDisplayDecision {
  const decisions = members.map((item) => item.signal_display_decision)
  if (decisions.includes('SHOW')) return 'SHOW'
  if (decisions.includes('REVIEW') || decisions.some((decision) => decision !== 'HOLD')) return 'REVIEW'
  return 'HOLD'
}

export function signalDecisionCards(cards: ProjectCard[], decision: SignalDisplayDecision) {
  return cards.filter((card) => signalDisplayDecision(card.members) === decision)
}

const permitSource = /-building-permits$/
const explicitDate = /\b(?:20\d{2}[/-]\d{1,2}[/-]\d{1,2}|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}(?:-\d{1,2})?,?\s+20\d{2})\b/i
const explicitPlace = /\b(?:in|at)\s+(?:the\s+)?([A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){1,4})/

function source(item: Opportunity) {
  return item.evidence[0]?.source_id ?? ''
}

const rrcOperatorPlaceholders = new Set(['n/a', 'na', 'none', 'null', 'unknown', 'unavailable'])

function currentRrcOperator(item: Opportunity) {
  const operators = item.evidence.flatMap((evidence) => {
    if (!evidence.assessment_current || evidence.source_id !== 'texas-rrc-drilling-permits') return []
    return (evidence.abstract ?? '').split(/\r\n|[\n\r\u2028\u2029]/)
      .flatMap((line) => {
        const match = /^\s*operator\s*:\s*(.*?)\s*$/i.exec(line)
        return match ? [match[1].trim()] : []
      })
      .filter((name) => name && !rrcOperatorPlaceholders.has(normalized(name)))
  })
  const unique = new Map(operators.map((name) => [normalized(name), name]))
  return unique.size === 1 ? [...unique.values()][0] : null
}

function normalized(value: string) {
  return value.normalize('NFKC').replace(/\s+/g, ' ').trim().toLocaleLowerCase('en-US')
}

function reportedAction(item: Opportunity) {
  const candidates = actionCandidates(item)
  return candidates.find((candidate) => permitWorkTitle(candidate) || actionWithPlaceAndDate(candidate)) ?? candidates[0] ?? ''
}

function structuredPermitDescriptions(abstract: string | null | undefined) {
  if (!abstract) return []
  let description = ''
  let structured = false
  for (const line of abstract.split(/\r?\n/)) {
    const match = line.match(/^\s*([a-z][a-z _-]*)\s*:\s*(.*?)\s*$/i)
    if (!match) continue
    structured = true
    const label = match[1].toLocaleLowerCase('en-US').replace(/[ _-]+/g, ' ')
    if (label === 'description' && match[2]) description = match[2]
  }
  if (!structured) return [abstract]
  return description.trim() && !/^(?:n\/?a|none|null|unknown|new|building permit|permit|addition|alteration|addition\s*\/\s*alteration|[-–—])$/i.test(description.trim())
    ? [description]
    : []
}

function actionCandidates(item: Opportunity) {
  const supported = item.supported_action?.trim()
  const candidates = supported ? [supported] : []
  const abstracts = item.evidence.flatMap((evidence) => structuredPermitDescriptions(evidence.abstract))
  return [...candidates, ...abstracts]
}

function actionWithPlaceAndDate(action: string) {
  return explicitDate.test(action) && explicitPlace.test(action)
}

function dateSuffix(action: string) {
  const full = action.match(/\b(january|february|march|april|may|june|july|august|september|october|november|december)\b[^|.;]{0,60}\b(20\d{2})\b/i)
  if (!full) return action.match(/\b(20\d{2})\b/)?.[1] ?? ''
  return `${full[1].slice(0, 3)} ${full[2]}`
}

function titleCase(value: string) {
  const acronyms = new Set(['ai', 'ats', 'cbc', 'cbrc', 'dc', 'mep', 'ng', 'pacu', 'sl100'])
  return value.toLocaleLowerCase('en-US').replace(/\b[a-z0-9]+\b/g, (word) =>
    acronyms.has(word) ? word.toLocaleUpperCase('en-US') : word[0].toLocaleUpperCase('en-US') + word.slice(1),
  )
}

function eventTitle(action: string) {
  const place = action.match(explicitPlace)?.[1]?.replace(/[.,]+$/, '')
  const date = dateSuffix(action)
  const describedWork = action.match(/\b(music stages?[^.|]*|food vendors?[^.|]*|art vendors?[^.|]*|hospitality programs?[^.|]*)/i)?.[0]
  if (place && describedWork) {
    return `${place} · ${titleCase(describedWork.replace(/\s+/g, ' ').replace(/[.;,|]+$/, ''))}${date ? ` · ${date}` : ''}`
  }
  return permitWorkTitle(action)
}

function permitWorkTitle(action: string) {
  let work = action.replace(/\s+/g, ' ').trim()
  if (work.includes('|')) work = work.split('|').at(-1)?.trim() ?? work
  work = work.replace(/^\(?\d{4}[/-]\d{1,2}[/-]\d{1,2}\)?\s*[|:)–-]*\s*/i, '')
  work = work.replace(/^ePlan:\s*Commercial Expedited Review\s*-\s*/i, '')
  work = work.replace(/^(?:DDS\s+)?20\d{2}\s+CBRC(?:\s*&\s*CBC)?:\s*/i, '')
  work = work.replace(/^SPR\s*\/\s*20\d{2}\s+CBC:\s*/i, '')
  work = work.replace(/^PERMIT EXPIRES ON[^.]*\.\s*/i, '')
  work = work.replace(/^ERECTION STARTS:[^.]*?ERECTION ENDS:[^.]*\.\s*/i, '')
  work = work.replace(/^20\d{2}\s+CBC[.: -]*\s*/i, '')
  work = work.replace(/^(?:SELF CERT\s*)?CBC\s*20\d{2}[.: -]*\s*/i, '')
  work = work.replace(/^REINSTATEMENT OF \d{4} PERMIT \d+\s+FOR THE\s+/i, '')
  work = work.replace(/^REINST(?:ATEMENT)? OF \d{4} PERMIT \d+\s+FOR THE\s+/i, '')
  work = work.replace(/\b(?:SELF CERT|SELF-CERT|CBC\s*20\d{2}|2019 CBC)\b/gi, '')
  work = work.replace(/\bIntl\./gi, 'International').replace(/\bSept\./gi, 'September').replace(/\bSt\.(?=\s)/gi, 'St')
  work = work.replace(/\s+/g, ' ').replace(/\bON ON\b/gi, 'ON').trim()
  const firstUsefulClause = work.split(/\.(?:\s|$)|\s+AS PER PLANS\b|\s+CONSTRUCTION TYPE\b/i)[0]?.trim()
  work = firstUsefulClause || work
  work = work.replace(/\s*\(\s*[\d,.]+\s*SF\s*\).*$/i, '')
  work = work.replace(/^[\s,.:;–-]+|[\s,.:;–-]+$/g, '')
  if (!work || /^\d+$/.test(work) || /^(?:row|date|status|document number)\s*:/i.test(work)
    || /^(?:new|building permit|permit|addition|alteration|addition\s*\/\s*alteration)$/i.test(work)) return ''
  const titled = titleCase(work)
  return titled.length > 92 ? `${titled.slice(0, 89).trimEnd()}…` : titled
}

function neutralTitle(item: Opportunity) {
  const labels: Record<string, string> = {
    'backup-power': 'Backup power',
    'event-power': 'Event power',
    'facility-expansion': 'Facility expansion',
    'temporary-power': 'Temporary power',
  }
  const activity = labels[item.activity] ?? titleCase(item.activity.replaceAll('-', ' '))
  return `${activity} · ${item.location ?? 'Location unknown'}`
}

function georgiaActivityTitle(item: Opportunity) {
  const text = item.supported_action?.trim().replace(/\s+/g, ' ') ?? ''
  if (!text) return neutralTitle(item)
  const rules: Array<[RegExp, string]> = [
    [/operations will be powered with [^.]{0,160}generator sets?[^.]{0,120}until grid power is available/i, 'Generators until grid power is available'],
    [/increasing the permitted production[^.]{0,100}(?:quarry|crushing)/i, 'Quarry production capacity increase'],
    [/modification and operation of this existing quarry/i, 'Quarry processing equipment modification'],
    [/adding a [^.]{0,100}portable stone processing plant/i, 'Quarry processing equipment expansion'],
    [/replac(?:e|ing) the existing permitted drum dryer and baghouse/i, 'Asphalt plant equipment replacement'],
    [/additional \d+ emergency generators/i, 'Additional emergency generators'],
    [/construction and operation of a [^.]{0,160}(?:landfill gas|LFG)[^.]{0,80}renewable natural gas[^.]{0,80}processing facility/i, 'Renewable natural gas facility construction'],
    [/construction and operation of diesel-fired emergency generators to provide backup power at a new data center/i, 'New data center backup generators'],
    [/construction and operation of a greenfield data center with \d+/i, 'New data center construction'],
    [/construction and operation of diesel emergency generators and diesel supporting emergency engines at a data processing facility/i, 'Data center backup generator installation'],
    [/(?:construct|construction of) (?:a )?(?:new )?(?:data center|data processing facility)/i, 'New data center construction'],
    [/(?:construct|construction of) (?:a )?(?:new )?(?:facility|data processing facility)/i, 'New facility construction'],
    [/(?:expand|expansion of) (?:the )?(?:facility|campus|data center)/i, 'Facility expansion'],
    [/(?:standby|backup) (?:diesel |natural gas )?generators?/i, 'Standby generator installation'],
    [/(?:construct|construction of) [^.]{0,90}(?:plant|mill|quarry|terminal|facility)/i, 'Facility construction'],
  ]
  for (const [pattern, title] of rules) {
    if (pattern.test(text)) return title
  }
  return neutralTitle(item)
}

function supportedCompany(item: Opportunity) {
  if (item.title_company?.trim() && item.title_company_role?.trim()) {
    return { name: item.title_company.trim(), role: item.title_company_role.trim() }
  }
  const rrcOperator = currentRrcOperator(item)
  if (rrcOperator) return { name: rrcOperator, role: 'RRC permit-listed operator · buyer authority UNKNOWN' }
  const candidates = item.evidence.flatMap((evidence) => {
    if (!evidence.assessment_current) return []
    const abstract = evidence.abstract ?? ''
    const pairs = [...abstract.matchAll(/^\s*(owner_company_name|operator_company_name|applicant_org|contractor_company_name|lp_business_name)\s*:\s*(.+?)\s*$/gim)]
    return pairs.map((match) => ({ key: match[1].toLocaleLowerCase('en-US'), name: match[2].trim() }))
  })
  for (const key of ['owner_company_name', 'operator_company_name', 'applicant_org']) {
    const found = candidates.find((candidate) => candidate.key === key && candidate.name && !/^unknown$/i.test(candidate.name))
    if (found) return { name: found.name, role: key === 'applicant_org' ? 'applicant' : key === 'owner_company_name' ? 'owner' : 'operator' }
  }
  const lpBusiness = candidates.find((candidate) => candidate.key === 'lp_business_name' && candidate.name && !/^unknown$/i.test(candidate.name))
  if (lpBusiness) return { name: lpBusiness.name, role: 'LP Business Name · role unverified' }
  const contractor = candidates.find((candidate) => candidate.key === 'contractor_company_name' && candidate.name && !/^unknown$/i.test(candidate.name))
  return contractor ? { name: contractor.name, role: 'contractor' } : null
}

export function projectTitle(item: Opportunity) {
  const company = supportedCompany(item)
  if (company) return `${company.name} · ${company.role}`
  if (source(item) === 'georgia-air-draft-title-v') return georgiaActivityTitle(item)
  if (/^(?:houston\s+)?permit\b/i.test(item.name)) return neutralTitle(item)
  if (!permitSource.test(source(item))) return item.name
  for (const action of actionCandidates(item)) {
    if (item.activity === 'event-power' && actionWithPlaceAndDate(action)) {
      const title = eventTitle(action)
      if (title) return title
    }
    const title = permitWorkTitle(action)
    if (title) return title
  }
  return neutralTitle(item)
}

function exactEventIdentity(item: Opportunity) {
  const action = reportedAction(item)
  const itemSource = source(item)
  if (!permitSource.test(itemSource) || !item.location || !action || !actionWithPlaceAndDate(action)) return null
  return [
    itemSource,
    normalized(item.location),
    normalized(item.tier),
    normalized(item.activity),
    normalized(action),
  ].join('\u001f')
}

export function projectCards(items: Opportunity[]): ProjectCard[] {
  const groups = new Map<string, Opportunity[]>()
  const projectCounts = new Map<string, number>()
  for (const item of items) {
    if (item.project_id) {
      const projectKey = `${item.tier}:${item.project_id}`
      projectCounts.set(projectKey, (projectCounts.get(projectKey) ?? 0) + 1)
    }
  }
  for (const item of items) {
    const projectKey = `${item.tier}:${item.project_id}`
    const hasSharedProjectId = Boolean(item.project_id && (projectCounts.get(projectKey) ?? 0) > 1)
    const identity = hasSharedProjectId ? `project:${item.tier}:${item.project_id}` : exactEventIdentity(item)
    const key = identity ?? (item.project_id ? `project:${item.tier}:${item.project_id}` : `record:${item.id}`)
    const members = groups.get(key) ?? []
    members.push(item)
    groups.set(key, members)
  }
  return [...groups.entries()].map(([key, members]) => ({
    key,
    title: projectTitle(members[0]),
    members,
    grouped: members.length > 1,
  }))
}

export function serverProjectCards(items: Opportunity[]): ProjectCard[] {
  const groups = new Map<string, Opportunity[]>()
  for (const item of items) {
    const key = item.group_id ?? `record:${item.id}`
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  return [...groups.entries()].map(([key, members]) => {
    const total = Math.max(...members.map((item) => item.group_total_filtered ?? members.length))
    return {
      key,
      title: members[0].group_title ?? projectTitle(members[0]),
      members,
      grouped: total > 1,
      groupTotal: total,
      complete: members.some((item) => item.group_complete_on_page === true) || members.length === total,
    }
  })
}

export function matchesOpportunity(item: Opportunity, query: string) {
  const term = normalized(query)
  if (!term) return true
  const searchable = [
    item.name,
    projectTitle(item),
    item.location ?? '',
    item.activity,
    item.supported_subject ?? '',
    item.supported_action ?? '',
    item.assessment_reason ?? '',
    ...item.evidence.flatMap((evidence) => [evidence.title, evidence.abstract ?? '', evidence.document_number, evidence.source_id]),
  ].join(' ')
  return normalized(searchable).includes(term)
}
