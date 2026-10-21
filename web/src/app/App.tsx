import { useEffect } from 'react'
import { WorkspaceHome } from '../features/workspace/Workspace'

// Every supported URL is handled by the same authenticated application shell.
export function App() {
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (location.pathname === '/environment' || params.get('view') === 'environment') {
      params.set('view', params.get('mode') === 'pursuits' ? 'pursuits' : 'workspace')
      history.replaceState(history.state, '', `/?${params}`)
    }
  }, [])
  return <WorkspaceHome />
}
