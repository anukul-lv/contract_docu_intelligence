import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { IngestPage } from './pages/IngestPage';
import { ExplorePage } from './pages/ExplorePage';
import { ReviewPage } from './pages/ReviewPage';
import { AdminPage } from './pages/AdminPage';
import { LoadingSpinner } from './components/common/LoadingSpinner';

// Lazy-load Chat page (R2) to keep initial bundle small
const ChatPage = lazy(() => import('./pages/ChatPage'));

export default function App() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingSpinner size="lg" label="Loading..." />}>
        <Routes>
          <Route path="/" element={<Navigate to="/ingest" replace />} />
          <Route path="/ingest" element={<IngestPage />} />
          <Route path="/explore" element={<ExplorePage />} />
          <Route path="/explore/:familyId" element={<ExplorePage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/admin" element={<AdminPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
