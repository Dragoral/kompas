import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { Layout } from './components/Layout'
import { homePath, RequireRole } from './components/RequireRole'
import { SystemPage } from './pages/admin/SystemPage'
import { UsersPage } from './pages/admin/UsersPage'
import { AlertsPage } from './pages/doctor/AlertsPage'
import { PatientPage } from './pages/doctor/PatientPage'
import { PatientsPage } from './pages/doctor/PatientsPage'
import { ImportScalePage } from './pages/knowledge/ImportScalePage'
import { KnowledgePage } from './pages/knowledge/KnowledgePage'
import { ReviewPage } from './pages/knowledge/ReviewPage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { DiaryPage } from './pages/patient/DiaryPage'
import { HomePage } from './pages/patient/HomePage'
import { ScalePage } from './pages/patient/ScalePage'

function Home() {
  const { user, loading } = useAuth()
  if (loading) return null
  return <Navigate to={user ? homePath(user.role) : '/login'} replace />
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<LoginPage />} />

      <Route element={<RequireRole roles={['doctor']}><Layout /></RequireRole>}>
        <Route path="/doctor/patients" element={<PatientsPage />} />
        <Route path="/doctor/patients/:id" element={<PatientPage />} />
        <Route path="/doctor/alerts" element={<AlertsPage />} />
        <Route path="/knowledge/review" element={<ReviewPage />} />
      </Route>

      <Route element={<RequireRole roles={['patient']}><Layout /></RequireRole>}>
        <Route path="/me" element={<HomePage />} />
        <Route path="/me/diary" element={<DiaryPage />} />
        <Route path="/me/scales/:code" element={<ScalePage />} />
      </Route>

      <Route element={<RequireRole roles={['doctor', 'admin']}><Layout /></RequireRole>}>
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/knowledge/import" element={<ImportScalePage />} />
      </Route>

      <Route element={<RequireRole roles={['admin']}><Layout /></RequireRole>}>
        <Route path="/admin/system" element={<SystemPage />} />
        <Route path="/admin/users" element={<UsersPage />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
