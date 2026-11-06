import { useEffect, useState, type ReactNode } from 'react'
import { client, type DemandSummary } from '../../api/client'
import { refreshPursuits, usePursuitStore } from '../../state/pursuitStore'
import { onPursuitDataEnded } from '../../state/sessionState'
import { WorkspaceChanges } from '../workspace/WorkspaceChanges'
import './reports.css'

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ok'; value: T }
function useLoad<T>(read: (signal: AbortSignal) => Promise<T>): [Load<T>, () => void] {
  const [state, setState] = useState<Load<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    read(controller.signal).then(value => { if (!controller.signal.aborted) setState({ status: 'ok', value }) })
      .catch((cause: unknown) => { if (!controller.signal.aborted) setState({ status: 'error', message: cause instanceof Error ? cause.message : 'Unavailable.' }) })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt])
  return [state, () => setAttempt(value => value + 1)]
}
const mw = (value: number) => `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} MW`
const classMw = (item: { mw: number | null; record_count: number }) => item.mw !== null ? mw(item.mw) : item.record_count > 0 ? 'Unknown' : 'No records'

function Tile({ title, definition, load, retry, children }: { title: string; definition: string; load: Load<unknown> | null; retry?: () => void; children?: ReactNode }) {
  return <article className="rpt-tile" aria-label={title}>
    <span className="rpt-label">{title}</span>
    {load?.status === 'loading' && <strong role="status" aria-label={`${title} loading`}>…</strong>}
    {load?.status === 'error' && <><strong>Unavailable</strong><small role="alert">{load.message} {retry && <button type="button" onClick={retry}>Retry</button>}</small></>}
    {(load === null || load.status === 'ok') && children}
    <small className="rpt-def">{definition}</small>
  </article>
}

// Unavailable has several causes (bound exceeded, no MW-bearing record); never turn it into "none" unless counts say so.
function unavailableText(summary: DemandSummary) {
  if (summary.counts_complete !== true) return 'Record counts are unavailable.'
  const t = summary.totals
  if (t.identified_records === 0) return 'No supported equipment demand records are available.'
  return `${t.identified_records.toLocaleString()} identified ${t.identified_records === 1 ? 'record' : 'records'} · ${t.known_mw_records.toLocaleString()} with MW · ${t.unknown_records.toLocaleString()} unknown · ${t.conflicted_records.toLocaleString()} conflicted. No MW total is available.`
}

function DemandBody({ summary }: { summary: DemandSummary }) {
  if (summary.availability !== 'available') return <><strong>Unavailable</strong><small>{unavailableText(summary)} Unknown is not zero.</small>{summary.limitations.map(item => <small key={item}>{item}</small>)}</>
  const complete = summary.counts_complete !== false
  return <>
    <strong>{complete ? `${summary.totals.identified_records.toLocaleString()} identified records` : 'Record counts incomplete'}</strong>
    <dl className="rpt-classes">{(['documented', 'calculated', 'estimated'] as const).map(key => <div key={key}><dt>{key[0].toUpperCase() + key.slice(1)}</dt><dd>{classMw(summary.classes[key])} · {summary.classes[key].record_count} {summary.classes[key].record_count === 1 ? 'record' : 'records'}</dd></div>)}</dl>
    {complete && <small>{summary.totals.known_mw_records} with MW · {summary.totals.unknown_records} unknown · {summary.totals.conflicted_records} conflicted.</small>}
    <small>Additional equipment only; not total portfolio demand. Classes are shown separately and are not summed. Unknown is not zero.</small>
    {summary.limitations.map(item => <small key={item}>{item}</small>)}
  </>
}

const TIERS = ['Signal', 'Prospect', 'Lead'] as const
async function tierCount(tier: string, signal: AbortSignal) {
  const page = await client.opportunityPage(tier, '', 'ALL', 1, 0, undefined, {}, signal)
  if (!page.totalCountKnown) throw new Error('The response did not include a total count.')
  return page.totalCount
}

export function ReportsPanel({ onSelectActiveNeed }: { onSelectActiveNeed: (need: { id: string }) => void }) {
  const [ended, setEnded] = useState(false)
  useEffect(() => {
    const onEnded = () => setEnded(true)
    return onPursuitDataEnded(onEnded)
  }, [])
  // Unmounting the body aborts in-flight requests and drops every loaded figure and change item.
  return ended ? <div className="rpt"><p role="alert">Your session ended. Sign in again.</p></div> : <ReportsBody onSelectActiveNeed={onSelectActiveNeed}/>
}

function ReportsBody({ onSelectActiveNeed }: { onSelectActiveNeed: (need: { id: string }) => void }) {
  const pursuits = usePursuitStore()
  useEffect(() => { if (!pursuits.loaded) void refreshPursuits() }, [pursuits.loaded])
  const [projects, retryProjects] = useLoad(signal => client.projectResults({ sector: 'all', limit: 1 }, signal))
  const [companies, retryCompanies] = useLoad(signal => client.opportunityGroups({ sector: 'all', limit: 1 }, signal))
  const [demand, retryDemand] = useLoad(signal => client.demandSummary('all', signal))
  const [oil, retryOil] = useLoad(signal => client.demandSummary('oil_gas', signal))
  const [dc, retryDc] = useLoad(signal => client.demandSummary('data_centers', signal))
  const [tiers, retryTiers] = useLoad(async signal => Promise.all(TIERS.map(async tier => ({ tier, count: await tierCount(tier, signal) }))))
  const pursuitLoad: Load<number> | null = !pursuits.loaded ? { status: 'loading' } : pursuits.error ? { status: 'error', message: pursuits.error } : null
  const max = tiers.status === 'ok' ? Math.max(...tiers.value.map(item => item.count)) : 0

  return <div className="rpt">
    <h1>Reports</h1>
    <p className="rpt-sub">Counts come from the current source-backed results. Each figure states what it measures.</p>
    <div className="rpt-tiles">
      <Tile title="Total Projects" definition={`Projects in the current project results${projects.status === 'ok' && projects.value.results_scope ? ` (${projects.value.results_scope} scope)` : ''}.`} load={projects} retry={retryProjects}>
        {projects.status === 'ok' && <strong>{projects.value.total.toLocaleString()}</strong>}
      </Tile>
      <Tile title="Operator/customer groups" definition="Groups in the current results. Includes one group per unresolved project and same-name groups, so this is not a count of confirmed companies." load={companies} retry={retryCompanies}>
        {companies.status === 'ok' && <strong>{companies.value.total.toLocaleString()}</strong>}
      </Tile>
      <Tile title="Active Pursuits" definition="Your commercial pursuits that are not Won or Lost." load={pursuitLoad} retry={() => void refreshPursuits(true)}>
        <strong>{pursuits.counts.active.toLocaleString()}</strong>
      </Tile>
      <Tile title="Identified Demand" definition="Equipment-based demand records by evidence class. Not total portfolio demand." load={demand} retry={retryDemand}>
        {demand.status === 'ok' && <DemandBody summary={demand.value}/>}
      </Tile>
    </div>
    <section className="rpt-card" aria-label="Activity and pipeline">
      <h2>Activity &amp; Pipeline</h2>
      <p className="rpt-def">Signal, Prospect and Lead qualification levels of current records, not Pursuit stages.</p>
      {tiers.status === 'loading' && <p role="status">Loading qualification counts…</p>}
      {tiers.status === 'error' && <p role="alert">Qualification counts are unavailable: {tiers.message} <button type="button" onClick={retryTiers}>Retry</button></p>}
      {tiers.status === 'ok' && <ul className="rpt-bars">{tiers.value.map(item => <li key={item.tier}><span>{item.tier}</span><span className="rpt-bar" aria-hidden="true"><i style={{ width: `${max ? Math.round(item.count / max * 100) : 0}%` }}/></span><b>{item.count.toLocaleString()}</b></li>)}</ul>}
    </section>
    <section className="rpt-card" aria-label="Identified demand by vertical">
      <h2>Identified demand by vertical</h2>
      <p className="rpt-def">Equipment-based records only, by evidence class. Not total portfolio demand; classes are not summed.</p>
      {([['Oil & Gas', oil, retryOil], ['Data Centers', dc, retryDc]] as const).map(([label, load, retry]) => <div key={label} className="rpt-vertical"><h3>{label}</h3>
        {load.status === 'loading' && <p role="status">Loading…</p>}
        {load.status === 'error' && <p role="alert">Unavailable: {load.message} <button type="button" onClick={retry}>Retry</button></p>}
        {load.status === 'ok' && (load.value.availability === 'available' ? <p>{(['documented', 'calculated', 'estimated'] as const).map(key => `${key[0].toUpperCase() + key.slice(1)} ${classMw(load.value.classes[key])}`).join(' · ')}</p> : <p>Unavailable: {unavailableText(load.value)}{load.value.limitations.map(item => <small key={item}> {item}</small>)}</p>)}
      </div>)}
    </section>
    <section className="rpt-card" aria-label="Not yet available">
      <h2>Not yet available</h2>
      <ul>
        <li><strong>Demand by Vertical chart:</strong> documented, calculated and estimated demand are different evidence classes and the API provides no combined share, so a donut would be invented.</li>
        <li><strong>Total portfolio demand (GW):</strong> the demand summary covers supported equipment records only.</li>
        <li><strong>High Priority and priority counts:</strong> not shown here; this view does not use the priority filters of the opportunity and group endpoints.</li>
        <li><strong>New This Week:</strong> not shown here; see the recent changes list below.</li>
      </ul>
    </section>
    <section className="rpt-card" aria-label="Export and recent changes">
      <h2>Export and changes</h2>
      <p>Export the current results with the table's Export action. Recent source-backed changes appear below.</p>
      <WorkspaceChanges onSelectActiveNeed={onSelectActiveNeed}/>
    </section>
  </div>
}
