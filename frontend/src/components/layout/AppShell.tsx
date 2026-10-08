import type { ReactNode } from 'react';
import { NavTabs } from './NavTabs';

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Top navigation bar */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <h1 className="text-lg font-semibold text-gray-900 whitespace-nowrap">
            HealthContracts AI
          </h1>
          <NavTabs />
        </div>
        <div className="flex items-center gap-3">
          <button
            className="text-sm text-gray-500 hover:text-gray-700"
            aria-label="Help"
          >
            ?
          </button>
        </div>
      </header>

      {/* Main content area */}
      <main className="flex-1 px-6 py-4 max-w-screen-2xl mx-auto w-full">
        {children}
      </main>
    </div>
  );
}
