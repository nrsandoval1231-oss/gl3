import { useEffect } from 'react'
import { WorkspaceHome } from '../features/workspace/Workspace'

// Every supported URL is handled by the same authenticated application shell.
export function App() {
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (location.pathname === '/environment' || params.get('view') === 'environment') {
      const mode = params.get('mode')
      const sections: Record<string, string> = {
        evidence: 'evidence', buyers: 'buying-chain', power: 'power-gap', action: 'next-steps',
      }
      const legacyTier = params.get('level')?.replace(/s$/i, '')
      const destination = mode === 'pursuits' ? 'pursuits' : mode === 'browse' ? 'signals' : 'workspace'
      params.set('view', destination)
      if (sections[mode ?? '']) params.set('section', sections[mode ?? ''])
      if (!params.has('industry') && params.has('lens')) params.set('industry', params.get('lens') ?? '')
      if (destination === 'signals') {
        if (legacyTier && ['Signal', 'Prospect', 'Lead'].includes(legacyTier)) params.set('tier', legacyTier)
        if (!params.has('offset') && params.has('records')) params.set('offset', params.get('records') ?? '0')
      }
      params.delete('mode'); params.delete('level'); params.delete('lens'); params.delete('records')
      history.replaceState(history.state, '', `/?${params}`)
    }
  }, [])
  return <WorkspaceHome />
}
