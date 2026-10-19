import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { Layout } from './components/Layout'
import { homePath, RequireRole } from './components/RequireRole'
import { AccountPage } from './pages/AccountPage'
import { AuditPage } from './pages/admin/AuditPage'
import { PatientsAdminPage } from './pages/admin/PatientsAdminPage'
import { SystemPage } from './pages/admin/SystemPage'
import { UsersPage } from './pages/admin/UsersPage'
import { AlertsPage } from './pages/doctor/AlertsPage'
import { NewPatientPage } from './pages/doctor/NewPatientPage'
import { ClinicianScalePage } from './pages/doctor/patient/ClinicianScalePage'
import { DataTab } from './pages/doctor/patient/DataTab'
import { HistoryTab } from './pages/doctor/patient/HistoryTab'
import { MessagesTab } from './pages/doctor/patient/MessagesTab'
import { OverviewTab } from './pages/doctor/patient/OverviewTab'
import { PatientLayout } from './pages/doctor/patient/PatientLayout'
import { ScalesTab } from './pages/doctor/patient/ScalesTab'
import { TherapyTab } from './pages/doctor/patient/TherapyTab'
import { PatientsPage } from './pages/doctor/PatientsPage'
import { DrugEditorPage } from './pages/knowledge/drug/DrugEditorPage'
import { ImportScalePage } from './pages/knowledge/ImportScalePage'
import { JsonEditorPage } from './pages/knowledge/JsonEditorPage'
import { KnowledgePage } from './pages/knowledge/KnowledgePage'
import { ResponsePolicyPage } from './pages/knowledge/ResponsePolicyPage'
import { ReviewPage } from './pages/knowledge/ReviewPage'
import { RulesEditorPage } from './pages/knowledge/rules/RulesEditorPage'
import { ScaleEditorPage } from './pages/knowledge/scale-editor/ScaleEditorPage'
import { VersionsPage } from './pages/knowledge/VersionsPage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { AdverseEventPage } from './pages/patient/AdverseEventPage'
import { DiaryPage } from './pages/patient/DiaryPage'
import { HistoryPage } from './pages/patient/HistoryPage'
import { HomePage } from './pages/patient/HomePage'
import { MessagesPage } from './pages/patient/MessagesPage'
import { MyDataPage } from './pages/patient/MyDataPage'
import { ScalePage } from './pages/patient/ScalePage'
import { TrustedContactsPage } from './pages/patient/TrustedContactsPage'

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

      <Route element={<RequireRole roles={['doctor', 'patient', 'admin']}><Layout /></RequireRole>}>
        <Route path="/account" element={<AccountPage />} />
      </Route>

      <Route element={<RequireRole roles={['doctor']}><Layout /></RequireRole>}>
        <Route path="/doctor/patients" element={<PatientsPage />} />
        <Route path="/doctor/patients/new" element={<NewPatientPage />} />
        <Route path="/doctor/patients/:id" element={<PatientLayout />}>
          <Route index element={<OverviewTab />} />
          <Route path="therapy" element={<TherapyTab />} />
          <Route path="scales" element={<ScalesTab />} />
          <Route path="history" element={<HistoryTab />} />
          <Route path="messages" element={<MessagesTab />} />
          <Route path="data" element={<DataTab />} />
        </Route>
        <Route path="/doctor/patients/:id/scales/:code" element={<ClinicianScalePage />} />
        <Route path="/doctor/alerts" element={<AlertsPage />} />
        <Route path="/knowledge/review" element={<ReviewPage />} />
      </Route>

      <Route element={<RequireRole roles={['patient']}><Layout /></RequireRole>}>
        <Route path="/me" element={<HomePage />} />
        <Route path="/me/diary" element={<DiaryPage />} />
        <Route path="/me/history" element={<HistoryPage />} />
        <Route path="/me/messages" element={<MessagesPage />} />
        <Route path="/me/adverse-event" element={<AdverseEventPage />} />
        <Route path="/me/data" element={<MyDataPage />} />
        <Route path="/me/trusted-contacts" element={<TrustedContactsPage />} />
        <Route path="/me/scales/:code" element={<ScalePage />} />
      </Route>

      <Route element={<RequireRole roles={['doctor', 'admin']}><Layout /></RequireRole>}>
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/knowledge/import" element={<ImportScalePage />} />
        <Route path="/knowledge/scales/new" element={<ScaleEditorPage />} />
        <Route path="/knowledge/scales/:code" element={<ScaleEditorPage />} />
        <Route path="/knowledge/drugs/new" element={<DrugEditorPage />} />
        <Route path="/knowledge/drugs/:code" element={<DrugEditorPage />} />
        <Route path="/knowledge/rules/:code" element={<RulesEditorPage />} />
        <Route path="/knowledge/response-policy" element={<ResponsePolicyPage />} />
        <Route path="/knowledge/:kind/:code/json" element={<JsonEditorPage />} />
      </Route>

      <Route element={<RequireRole roles={['admin']}><Layout /></RequireRole>}>
        <Route path="/admin/system" element={<SystemPage />} />
        <Route path="/admin/users" element={<UsersPage />} />
        <Route path="/admin/audit" element={<AuditPage />} />
        <Route path="/admin/patients" element={<PatientsAdminPage />} />
        <Route path="/knowledge/:kind/:code/versions" element={<VersionsPage />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
