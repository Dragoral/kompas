import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { Role } from '../api/types'

export function homePath(role: Role): string {
  return { doctor: '/doctor/patients', patient: '/me', admin: '/admin/system' }[role]
}

export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <p className="container muted">Загрузка…</p>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (!roles.includes(user.role)) return <Navigate to={homePath(user.role)} replace />
  if ((user.must_change_password || user.mfa_setup_required) && location.pathname !== '/account') return <Navigate to="/account" replace />
  return <>{children}</>
}
