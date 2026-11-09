import { AuthProvider, useAuth } from './auth/AuthContext'
import { Dashboard } from './components/Dashboard'
import { LoginPage } from './components/LoginPage'

function Shell() {
  const { session } = useAuth()
  return session ? <Dashboard /> : <LoginPage />
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}
