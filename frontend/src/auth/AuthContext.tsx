import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, getToken, setToken, setUnauthorizedHandler } from '../api/client'
import type { LoginResponse, User } from '../api/types'
import { setOfflineQueueUser } from '../api/offlineQueue'

interface AuthState {
  user: User | null
  loading: boolean
  login: (login: string, password: string, totp?: string) => Promise<User>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => getToken() !== null)

  useEffect(() => {
    setOfflineQueueUser(user?.role === 'patient' ? user.id : null)
  }, [user?.id, user?.role])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null)
      setUser(null)
    })
    if (!getToken()) return
    api.get<User>('/api/auth/me')
      .then((u) => { setUser(u); setOfflineQueueUser(u.role === 'patient' ? u.id : null) })
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (login: string, password: string, totp?: string) => {
    const res = await api.post<LoginResponse>('/api/auth/login', { login, password, totp: totp || undefined })
    setToken(res.token)
    setUser(res.user)
    setOfflineQueueUser(res.user.role === 'patient' ? res.user.id : null)
    return res.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.post('/api/auth/logout')
    } finally {
      setToken(null)
      setUser(null)
      setOfflineQueueUser(null)
    }
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth вне AuthProvider')
  return ctx
}
