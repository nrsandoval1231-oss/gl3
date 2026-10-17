import { useRef, useState, type FormEvent } from 'react'
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
    <section className="login-scene" aria-label="GridLens infrastructure intelligence">
      <img className="login-scene-image" src="/images/login-infrastructure.png" alt="" />
      <div className="login-scene-shade" />
      <div className="login-brandplate"><img className="login-lockup" src="/brand/lockup-horizontal-white.svg" alt="GridLens" /></div>
      <div className="login-scene-caption"><span>GRIDLENS / INFRASTRUCTURE INTELLIGENCE</span><p>See what’s taking shape.<br/>Know where power matters.</p></div>
    </section>
    <section className="login-panel">
      <div className="login-panel-inner">
        <p className="login-kicker">PRIVATE WORKSPACE</p>
        <h1>Sign in</h1>
        <p className="login-intro">Your GridLens workspace brings emerging power needs into focus.</p>
        <form className="login-form" onSubmit={submit} aria-busy={pending}>
          <label htmlFor="login-password">Password</label>
          <div className="login-input-wrap">
            <input id="login-password" name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required aria-invalid={Boolean(error)} aria-describedby={error ? 'login-error' : undefined} />
            <button className="login-reveal" type="button" aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} onClick={() => setVisible((value) => !value)}>{visible ? 'Hide' : 'Show'}</button>
          </div>
          {error && <p className="login-error" id="login-error" role="alert">{error}</p>}
          <button className="login-submit" type="submit" disabled={pending}>{pending ? 'Signing in' : 'Continue'}</button>
          {pending && <p className="login-pending" role="status">Signing in to your private workspace.</p>}
        </form>
        <p className="login-security">Access is limited to your private workspace.</p>
      </div>
    </section>
  </main>
}
