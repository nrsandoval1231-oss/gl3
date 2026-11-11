import { useRef, useState, type FormEvent } from 'react'
import { ArrowRight, ChartNoAxesColumnIncreasing, Crosshair, Eye, EyeOff, Layers, LockKeyhole } from 'lucide-react'
import './login.css'

function loginErrorMessage(cause: unknown) {
  if (cause instanceof TypeError) return 'GridLens could not be reached. Check your connection and try again.'
  const detail = cause instanceof Error ? cause.message : ''
  const status = Number(detail.match(/\((\d{3})\)/)?.[1])
  if (status === 429) return 'Too many sign-in attempts. Wait a moment, then try again.'
  if (status >= 500 && status < 600) return 'Sign-in is temporarily unavailable. Try again shortly.'
  if (status === 401 || detail.includes('Your session ended')) return 'That password was not accepted. Check it and try again.'
  return 'We could not sign you in. Try again.'
}

export function LoginPage({ onLogin }: { onLogin: (password: string) => Promise<void> }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [visible, setVisible] = useState(false)
  const inFlight = useRef(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (inFlight.current) return
    inFlight.current = true
    setPending(true)
    setError('')
    try {
      await onLogin(password)
      setPassword('')
    } catch (cause) {
      setError(loginErrorMessage(cause))
      requestAnimationFrame(() => document.getElementById('login-password')?.focus())
    } finally {
      inFlight.current = false
      setPending(false)
    }
  }

  return <main className="login-page">
    <section className="login-story" aria-label="GridLens commercial intelligence">
      <picture className="login-architecture" aria-hidden="true">
        <source media="(min-width: 641px)" srcSet="/ui/sign-in/architecture.webp" />
        <img src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="" width="960" height="1200" />
      </picture>
      <div className="login-story-content">
        <img className="login-story-logo" src="/brand/logos/horizontal-light.svg" alt="GridLens" width="1000" height="240" />
        <p className="login-tagline">Commercial Intelligence<br />for Constrained Power</p>
        <div className="login-accent" aria-hidden="true" />
        <h2>Real projects. <br />Real power.</h2>
        <ul className="login-stages" aria-label="Identify, qualify, pursue">
          <li><Crosshair aria-hidden="true" /><span>Identify</span></li>
          <li><Layers aria-hidden="true" /><span>Qualify</span></li>
          <li><ChartNoAxesColumnIncreasing aria-hidden="true" /><span>Pursue</span></li>
        </ul>
      </div>
    </section>
    <section className="login-panel" aria-labelledby="login-title">
      <div className="login-panel-inner">
        <p className="login-kicker">PRIVATE WORKSPACE</p>
        <h1 id="login-title">Sign in to GridLens</h1>
        <p className="login-intro">Enter your workspace password to continue.</p>
        <form className="login-form" onSubmit={submit} aria-busy={pending}>
          <label htmlFor="login-password">Password</label>
          <div className="login-input-wrap">
            <LockKeyhole className="login-input-icon" aria-hidden="true" size={22} />
            <input id="login-password" name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Password" required aria-invalid={Boolean(error)} aria-describedby={error ? 'login-error' : undefined} />
            <button className="login-reveal" type="button" aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} onClick={() => setVisible((value) => !value)}>{visible ? <EyeOff aria-hidden="true" size={22} /> : <Eye aria-hidden="true" size={22} />}</button>
          </div>
          {error && <p className="login-error" id="login-error" role="alert">{error}</p>}
          <button className="login-submit" type="submit" disabled={pending}>{pending ? 'Signing in' : 'Sign in'}<ArrowRight aria-hidden="true" size={22} /></button>
          {pending && <p className="login-pending" role="status">Signing in to your private workspace.</p>}
        </form>
        <p className="login-recovery">Need help signing in?<br /><span>Contact your workspace administrator</span> to recover access.</p>
        <p className="login-security"><LockKeyhole aria-hidden="true" size={15} />Access is limited to your private workspace.</p>
      </div>
    </section>
  </main>
}
