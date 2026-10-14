import { lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { WorkspacePage } from './pages/WorkspacePage'

// Pages other than the main workspace are code-split, so charting code is
// only downloaded when a page that needs it is opened.
const SqlViewerPage = lazy(() => import('./pages/SqlViewerPage').then((m) => ({ default: m.SqlViewerPage })))
const ResultsPage = lazy(() => import('./pages/ResultsPage').then((m) => ({ default: m.ResultsPage })))
const SchemaPage = lazy(() => import('./pages/SchemaPage').then((m) => ({ default: m.SchemaPage })))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage })))
const HistoryPage = lazy(() => import('./pages/HistoryPage').then((m) => ({ default: m.HistoryPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then((m) => ({ default: m.NotFoundPage })))

export default function App() {
  return (
    <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<WorkspacePage />} />
          <Route path="sql" element={<SqlViewerPage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="schema" element={<SchemaPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
    </Routes>
  )
}
