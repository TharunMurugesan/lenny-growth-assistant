/* Persisted UI preferences: theme, provider choice, artifact pane width.
 *
 * All three survive a reload because all three are decisions the user made
 * about how they want to work, and re-making them every visit is friction. */

import { useCallback, useEffect, useState } from 'react'

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? fallback : JSON.parse(raw)
  } catch {
    return fallback
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* private mode / quota — preference simply does not persist */
  }
}

export function usePersistent(key, fallback) {
  const [value, setValue] = useState(() => read(key, fallback))
  const set = useCallback(
    (next) => {
      setValue((prev) => {
        const resolved = typeof next === 'function' ? next(prev) : next
        write(key, resolved)
        return resolved
      })
    },
    [key]
  )
  return [value, set]
}

/* --- Theme --------------------------------------------------------------
 * Three states, not two: System is the default, because an app that ignores
 * the OS preference is making a decision that is not its to make. The raw
 * string is stored (not JSON) so the inline script in index.html — which runs
 * before any JS module — can read it without a parser. */

const THEME_KEY = 'lga:theme'

export function useTheme() {
  const [preference, setPreference] = useState(() => {
    try {
      return localStorage.getItem(THEME_KEY) || 'system'
    } catch {
      return 'system'
    }
  })

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')

    const apply = () => {
      const dark = preference === 'dark' || (preference === 'system' && media.matches)
      document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    }

    apply()
    try {
      localStorage.setItem(THEME_KEY, preference)
    } catch {
      /* ignore */
    }

    // Only follow the OS while the preference *is* System.
    if (preference !== 'system') return undefined
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [preference])

  const cycle = useCallback(() => {
    setPreference((p) => (p === 'system' ? 'light' : p === 'light' ? 'dark' : 'system'))
  }, [])

  return { preference, setPreference, cycle }
}
