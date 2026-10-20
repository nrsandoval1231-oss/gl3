// Location strings come from sources ("Dallas, Texas", "Austin, TX"). Resolve only an
// explicit state name or postal code; anything else stays unmapped and listed.
const stateCodes: Record<string, string> = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado',
  CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia',
  HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas',
  KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts',
  MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana',
  NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico',
  NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma',
  OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota',
  TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington',
  WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming',
}
const names = Object.values(stateCodes).sort((a, b) => b.length - a.length)

export function stateOf(location: string | null | undefined): string | null {
  if (!location) return null
  // A trailing postal code is the most explicit signal ("Washington, DC" is not Washington state).
  const code = location.match(/(?:,|\s)\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$/)
  if (code && stateCodes[code[1]]) return stateCodes[code[1]]
  const lower = location.toLowerCase()
  if (/\bdistrict of columbia\b/.test(lower)) return stateCodes.DC
  for (const name of names) {
    if (new RegExp(`\\b${name.toLowerCase()}\\b`).test(lower)) return name
  }
  return null
}
