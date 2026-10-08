import { CheckCircle, Sparkles, Pencil, Flag, AlertTriangle, AlertCircle } from 'lucide-react';
import type { TrustBadgeType } from '@/lib/types';
import { TRUST_BADGES } from '@/lib/constants';

const ICON_MAP = { CheckCircle, Sparkles, Pencil, Flag, AlertTriangle, AlertCircle };

const COLOR_CLASSES: Record<string, string> = {
  green: 'bg-green-100 text-green-800',
  yellow: 'bg-yellow-100 text-yellow-800',
  blue: 'bg-blue-100 text-blue-800',
  red: 'bg-red-100 text-red-800',
  orange: 'bg-orange-100 text-orange-800',
  purple: 'bg-purple-100 text-purple-800',
};

interface TrustBadgeProps {
  type: TrustBadgeType;
  size?: 'sm' | 'md';
}

export function TrustBadge({ type, size = 'md' }: TrustBadgeProps) {
  const config = TRUST_BADGES[type];
  if (!config) return null;

  const Icon = ICON_MAP[config.icon as keyof typeof ICON_MAP];
  const sizeClasses = size === 'sm' ? 'text-xs px-1.5 py-0.5' : 'text-sm px-2 py-1';
  const iconSize = size === 'sm' ? 'w-3 h-3' : 'w-4 h-4';

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-medium ${COLOR_CLASSES[config.color]} ${sizeClasses}`}
      role="status"
      aria-label={`Trust status: ${config.label}`}
    >
      {Icon && <Icon className={iconSize} aria-hidden="true" />}
      {config.label}
    </span>
  );
}
