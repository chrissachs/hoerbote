import { useState, type FormEvent } from 'react'
import { login } from './api'
import { SiteLinks } from './Imprint'
import { Masthead } from './Masthead'
import { routeHash } from './route'

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState('')
  const [state, setState] = useState<'idle' | 'busy' | 'wrong' | 'error'>('idle')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setState('busy')
    try {
      if (await login(password)) onSuccess()
      else setState('wrong')
    } catch {
      setState('error')
    }
  }

  return (
    <div className="login">
      <Masthead />
      <form onSubmit={submit}>
        <p className="muted">Mit dem Passwort sind auch die Ausgaben zu hören, die nicht frei lizenziert sind.</p>
        <label>
          Passwort
          <input type="password" autoFocus autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" disabled={!password || state === 'busy'}>Anmelden</button>
        {state === 'wrong' && <p className="error">Falsches Passwort.</p>}
        {state === 'error' && <p className="error">Anmeldung fehlgeschlagen -- bitte nochmal versuchen.</p>}
        <a className="back-link" href={routeHash(null)}>Zur Startseite</a>
      </form>
      <SiteLinks />
    </div>
  )
}
