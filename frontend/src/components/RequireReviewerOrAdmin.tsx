import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { homePath } from './RequireRole'

export function RequireReviewerOrAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <p className="container muted">Загрузка…</p>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (user.role !== 'admin' && !(user.role === 'doctor' && user.is_reviewer)) return <Navigate to={homePath(user.role)} replace />
  return <>{children}</>
}
