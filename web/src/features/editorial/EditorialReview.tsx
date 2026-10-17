import { useEffect, useRef, useState, type FormEvent } from 'react'

type Candidate = {
  id: string
  evidenceId: string
  evidenceHash: string
  title: string
  text: string
  sourceUrl: string
  publisher: string
  publishedAt: string | null
  geography: string
  industries: string[]
  eligibilityReason: string | null
  clearance: string
  reviewedAt: string | null
  reviewer: string | null
  assessment?: Assessment | null
}
type Assessment = {
  status: string
  reason?: string
  assessment?: {
    whatHappened: string
    whatChanged: string
    whyItMatters: string
    audiences: string[]
    powerGapAngle: string
    linkedInAngle: string
    evidenceGaps: string[]
    recommendation: string
    reason: string
  }
}
async function api(path: string, body?: unknown) {
  const r = await fetch('/api/editorial/' + path, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...(body === undefined
      ? {}
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }),
  })
  if (!r.ok)
    throw new Error((await r.json()).detail || 'Editorial request failed')
  return r.json()
}
export function EditorialReview() {
  const [items, setItems] = useState<Candidate[]>([])
  const [note, setNote] = useState('Loading retained evidence…')
  const load = () =>
    api('review')
      .then((v) => {
        setItems(v.items)
        setNote(
          `${v.items.length} retained public-source records. Clearance is separate from commercial qualification.`,
        )
      })
      .catch((e) => setNote(e.message))
  useEffect(() => {
    void load()
  }, [])
  return (
    <main className="env env-editorial">
      <header className="env-header">
        <a href="/?view=environment" className="env-brand">
          <img src="/brand/lockup-horizontal-white.svg" alt="GridLens" />
        </a>
        <h1>Editorial review</h1>
        <p>
          Review the source, assess reader value, and clear one evidence version
          for editorial use.
        </p>
      </header>
      <p role="status">{note}</p>
      {items.map((c) => (
        <Review key={c.id + ':' + c.evidenceHash} c={c} refresh={load} />
      ))}
    </main>
  )
}
function Review({
  c,
  refresh,
}: {
  c: Candidate
  refresh: () => Promise<void>
}) {
  const [judgment, setJudgment] = useState<Assessment | null>(
    c.assessment || null,
  )
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  async function assess() {
    setBusy(true)
    try {
      const result: Assessment = await api('assessment/' + c.id, {})
      setJudgment(result)
      if (result.assessment) {
        const a = result.assessment
        const suggestions: Record<string, string> = {
          commercialSignificance: a.whyItMatters,
          technicalImplications: a.whyItMatters,
          editorialAngles: [a.powerGapAngle, a.linkedInAngle].join('\n'),
          unknowns: a.evidenceGaps.join('\n'),
          interpretations: a.whyItMatters,
          whyNow: a.reason,
        }
        for (const [name, value] of Object.entries(suggestions)) {
          const field = formRef.current?.elements.namedItem(name)
          // Suggestions never overwrite the operator's writing or attestations.
          if (field instanceof HTMLTextAreaElement && !field.value.trim())
            field.value = value
        }
      }
    } catch (e) {
      setNote(String(e))
    } finally {
      setBusy(false)
    }
  }
  async function decide(status: string, review?: unknown) {
    setBusy(true)
    try {
      await api('review/' + c.id, {
        evidenceHash: c.evidenceHash,
        status,
        review,
      })
      await refresh()
      setNote('Decision retained for this evidence version.')
    } catch (e) {
      setNote(String(e))
    } finally {
      setBusy(false)
    }
  }
  function approve(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const data = new FormData(e.currentTarget)
    const text = (k: string) => String(data.get(k) || '')
    const lines = (k: string) =>
      text(k)
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
    const review = {
      title: c.title,
      geography: text('geography'),
      industry: text('industry'),
      eventClassification: text('eventClassification'),
      whatChanged: text('whatChanged'),
      verifiedFacts: lines('verifiedFacts'),
      unknowns: lines('unknowns'),
      interpretations: lines('interpretations'),
      hypotheses: [],
      commercialSignificance: text('commercialSignificance'),
      technicalImplications: text('technicalImplications'),
      editorialAngles: lines('editorialAngles'),
      whyNow: text('whyNow'),
      recommendedArticleType: text('recommendedArticleType'),
      evidenceQuality: text('evidenceQuality'),
      confidence: text('confidence'),
      review: {
        classificationVerified: true,
        publicOnly: true,
        ...Object.fromEntries(
          [
            'readerValue',
            'specificity',
            'significance',
            'originality',
            'technicalRelevance',
          ].map((k) => [k, Number(data.get(k))]),
        ),
      },
    }
    void decide('approved', review)
  }
  const a = judgment?.assessment
  return (
    <article className="env-evidence">
      <h2>{c.title}</h2>
      <p>
        <a href={c.sourceUrl} target="_blank" rel="noreferrer">
          {c.publisher}
        </a>{' '}
        · {c.publishedAt || 'Date unknown'} · {c.clearance}
      </p>
      <p>
        {c.eligibilityReason
          ? `Not eligible: ${c.eligibilityReason}`
          : 'Source and date checks passed; editorial relevance requires review.'}
      </p>
      <details>
        <summary>Inspect retained evidence</summary>
        <blockquote style={{ whiteSpace: 'pre-wrap' }}>
          {c.text || c.title}
        </blockquote>
        <small>
          Version {c.evidenceHash} ·{' '}
          {c.reviewedAt
            ? `Reviewed ${c.reviewedAt} by ${c.reviewer}`
            : 'Not reviewed'}
        </small>
      </details>
      {!c.eligibilityReason && (
        <>
          <button disabled={busy} onClick={() => void assess()}>
            Assess editorial value
          </button>
          {judgment && !a && <p role="status">{judgment.reason}</p>}
          {a && (
            <section>
              <p>
                AI interpretation — human verification required. No publication
                clearance.
              </p>
              <h3>{a.recommendation}</h3>
              <p>{a.reason}</p>
              <p>What happened: {a.whatHappened}</p>
              <p>What changed: {a.whatChanged}</p>
              <p>Why it matters: {a.whyItMatters}</p>
              <p>Who should care: {a.audiences.join(', ')}</p>
              <p>Power Gap Report: {a.powerGapAngle}</p>
              <p>LinkedIn: {a.linkedInAngle}</p>
              <p>Gaps: {a.evidenceGaps.join(' ')}</p>
            </section>
          )}
          <details>
            <summary>Review for editorial clearance</summary>
            <form
              ref={formRef}
              onSubmit={approve}
              style={{ display: 'grid', gap: 12, maxWidth: 900 }}
            >
              <label>
                Geography
                <input
                  name="geography"
                  required
                  placeholder="United States / state / city"
                />
              </label>
              <label>
                Industry
                <input name="industry" required />
              </label>
              <label>
                Event classification
                <select
                  aria-label="Event classification"
                  required
                  defaultValue=""
                  name="eventClassification"
                >
                  <option value="" disabled>
                    Choose the event supported by the evidence
                  </option>
                  {[
                    'permitting',
                    'project-milestone',
                    'electricity-availability',
                    'utility-infrastructure',
                    'fuel-infrastructure',
                    'equipment-schedule',
                    'energy-market',
                  ].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              {[
                'whatChanged',
                'verifiedFacts',
                'unknowns',
                'interpretations',
                'commercialSignificance',
                'technicalImplications',
                'editorialAngles',
                'whyNow',
              ].map((k) => (
                <label key={k}>
                  {
                    (
                      {
                        whatChanged: 'What changed — exact retained excerpt',
                        verifiedFacts: 'Factual excerpts — one per line',
                        unknowns: 'Evidence gaps — one per line',
                        interpretations:
                          'Analytical interpretations — one per line',
                        commercialSignificance: 'Why it matters commercially',
                        technicalImplications: 'Technical implications',
                        editorialAngles:
                          'Potential editorial angles — one per line',
                        whyNow: 'Why now / distinction from prior coverage',
                      } as Record<string, string>
                    )[k]
                  }
                  <textarea
                    name={k}
                    required={k !== 'interpretations'}
                    maxLength={1200}
                    defaultValue={
                      k === 'whatChanged' || k === 'verifiedFacts'
                        ? c.title
                        : undefined
                    }
                  />
                </label>
              ))}
              <label>
                Article type
                <select aria-label="Article type" name="recommendedArticleType">
                  {[
                    'research-brief',
                    'deep-dive',
                    'email-roundup',
                    'educational',
                  ].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                Evidence quality
                <select
                  aria-label="Evidence quality"
                  name="evidenceQuality"
                  required
                  defaultValue=""
                >
                  <option value="" disabled>
                    Choose source quality
                  </option>
                  <option>primary</option>
                  <option>reported</option>
                </select>
              </label>
              <label>
                Confidence
                <select
                  aria-label="Confidence"
                  name="confidence"
                  required
                  defaultValue=""
                >
                  <option value="" disabled>
                    Choose support level
                  </option>
                  <option>medium</option>
                  <option>high</option>
                  <option>low</option>
                </select>
              </label>
              {[
                'readerValue',
                'specificity',
                'significance',
                'originality',
                'technicalRelevance',
              ].map((k) => (
                <label key={k}>
                  {
                    (
                      {
                        readerValue: 'Reader usefulness',
                        specificity: 'Specificity',
                        significance: 'Commercial significance',
                        originality: 'Originality',
                        technicalRelevance: 'Technical relevance',
                      } as Record<string, string>
                    )[k]
                  }
                  <select name={k} required defaultValue="">
                    <option value="" disabled>
                      Select evidence-supported value
                    </option>
                    {[0, 1, 2, 3].map((v) => (
                      <option key={v} value={v}>
                        {['Absent', 'Weak', 'Supported', 'Strong'][v]}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              <label>
                <input type="checkbox" required /> I verified the classification
                and confirm all content is public and authorized, with no
                confidential intelligence.
              </label>
              <button disabled={busy}>Approve this evidence version</button>
            </form>
          </details>
          <button disabled={busy} onClick={() => void decide('needs-evidence')}>
            Request more evidence
          </button>
          <button disabled={busy} onClick={() => void decide('rejected')}>
            Reject
          </button>
        </>
      )}
      <p role="status">{note}</p>
    </article>
  )
}
