import './app-shell.css'
import { AppSidebar } from '@/components/app/app-sidebar'
import { AppTopbar } from '@/components/app/app-topbar'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app">
      <AppSidebar />
      <div className="main">
        <AppTopbar />
        <div className="content">{children}</div>
      </div>
    </div>
  )
}
