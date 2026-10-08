import { NavLink } from 'react-router-dom';
import { Upload, Search, CheckSquare, MessageSquare, Settings } from 'lucide-react';
import { NAV_TABS } from '@/lib/constants';

const ICONS: Record<string, typeof Upload> = {
  Upload,
  Search,
  CheckSquare,
  MessageSquare,
  Settings,
};

export function NavTabs() {
  return (
    <nav className="flex gap-1" role="tablist" aria-label="Main navigation">
      {NAV_TABS.map((tab) => {
        const Icon = ICONS[tab.icon];
        return (
          <NavLink
            key={tab.path}
            to={tab.path}
            role="tab"
            className={({ isActive }) =>
              `flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
              }`
            }
          >
            {Icon && <Icon className="w-4 h-4" />}
            {tab.label}
          </NavLink>
        );
      })}
    </nav>
  );
}
