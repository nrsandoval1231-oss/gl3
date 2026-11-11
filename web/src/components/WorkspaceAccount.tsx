import { useEffect, useRef, useState } from 'react'
import { ChevronDown, CircleUserRound } from 'lucide-react'
import './workspace-account.css'

export type WorkspaceAccountProps = {
  onResearch: () => void
  onSignals: () => void
  onDiagnostics: () => void
  onSignOut: () => void
}

const preferenceKey = 'gl3.reduceMotion'
const buildInfo = {
  environment: import.meta.env.VITE_DEPLOYMENT_ENVIRONMENT || 'Unavailable',
  version: import.meta.env.VITE_APP_VERSION || '0.1.0',
  sha: import.meta.env.VITE_GIT_SHA || 'Unavailable',
  deployedAt: import.meta.env.VITE_DEPLOYED_AT || 'Unavailable',
}

export function WorkspaceAccount({ onResearch, onSignals, onDiagnostics, onSignOut }: WorkspaceAccountProps) {
  const [open, setOpen] = useState(false)
  const [dialog, setDialog] = useState<'profile' | 'settings' | null>(null)
  const [reduceMotion, setReduceMotion] = useState(() => {
    try { return localStorage.getItem(preferenceKey) === 'true' } catch { return false }
  })
  const menu = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    document.documentElement.classList.toggle('gl3-reduce-motion', reduceMotion)
  }, [reduceMotion])

  useEffect(() => {
    if (!open) return
    const dismiss = (event: PointerEvent) => { if (!menu.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', dismiss)
    return () => { document.removeEventListener('pointerdown', dismiss) }
  }, [open])

  useEffect(() => {
    const node = dialogRef.current
    if (!node || !dialog) return
    node.showModal()
    closeButton.current?.focus()
    return () => { if (node.open) node.close() }
  }, [dialog])

  const closeDialog = () => {
    dialogRef.current?.close()
    setDialog(null)
    trigger.current?.focus()
  }

  const saveMotion = (enabled: boolean) => {
    setReduceMotion(enabled)
    try { localStorage.setItem(preferenceKey, String(enabled)) } catch { /* preference remains active for this session */ }
    document.documentElement.classList.toggle('gl3-reduce-motion', enabled)
  }
  const action = (callback: () => void) => { setOpen(false); callback() }

  return <div className="workspace-account" ref={menu}>
    <button ref={trigger} type="button" className="workspace-account__trigger" aria-label="Account menu" aria-controls="workspace-account-options" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <CircleUserRound size={22} strokeWidth={1.7} aria-hidden="true" />
      <ChevronDown className="workspace-account__chevron" size={13} strokeWidth={2} aria-hidden="true" />
    </button>
    {open && <div id="workspace-account-options" className="workspace-account__menu" aria-label="Account options">
      <div className="workspace-account__identity">Private workspace</div>
      <button onClick={() => action(() => setDialog('profile'))}>Profile</button>
      <button onClick={() => action(() => setDialog('settings'))}>Settings</button>
      <div className="workspace-account__separator" />
      <button onClick={() => action(onResearch)}>Research progress</button>
      <button onClick={() => action(onSignals)}>Signals</button>
      <button onClick={() => action(onDiagnostics)}>Technical diagnostics</button>
      <div className="workspace-account__separator" />
      <dl className="workspace-account__build" aria-label="Build information">
        <div><dt>Environment</dt><dd>{buildInfo.environment}</dd></div>
        <div><dt>Version</dt><dd>{buildInfo.version}</dd></div>
        <div><dt>Build SHA</dt><dd>{buildInfo.sha}</dd></div>
        <div><dt>Deployed</dt><dd>{buildInfo.deployedAt}</dd></div>
      </dl>
      <button className="workspace-account__signout" onClick={() => action(onSignOut)}>Sign out</button>
    </div>}
    <dialog ref={dialogRef} className="workspace-account__dialog" aria-labelledby="workspace-account-dialog-title" onClose={() => { setDialog(null); trigger.current?.focus() }}>
      {dialog && <>
        <button ref={closeButton} type="button" className="workspace-account__close" aria-label="Close dialog" onClick={closeDialog}>×</button>
        {dialog === 'profile' ? <><h2 id="workspace-account-dialog-title">Profile</h2><p>This private workspace uses a shared password session. No individual account identity or profile details are available.</p></> : <><h2 id="workspace-account-dialog-title">Settings</h2><label className="workspace-account__preference"><input type="checkbox" checked={reduceMotion} onChange={event => saveMotion(event.target.checked)} /> Reduce motion</label><p>This preference is saved in this browser.</p></>}
      </>}
    </dialog>
  </div>
}
