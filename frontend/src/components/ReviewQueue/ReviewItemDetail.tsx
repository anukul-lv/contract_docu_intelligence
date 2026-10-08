import { useState } from 'react';
import { Check, Pencil, Flag, ArrowLeft } from 'lucide-react';
import { useReviewActions } from '@/hooks/useReviewActions';
import { TrustBadge } from '@/components/TrustBadge/TrustBadge';
import { ConfidenceExplainer } from '@/components/ConfidenceExplainer/ConfidenceExplainer';
import type { ReviewItem, TrustBadgeType } from '@/lib/types';

interface ReviewItemDetailProps {
  item: ReviewItem;
  onBack: () => void;
}

export function ReviewItemDetail({ item, onBack }: ReviewItemDetailProps) {
  const actions = useReviewActions();
  const [correcting, setCorrecting] = useState(false);
  const [correctedValue, setCorrectedValue] = useState('');
  const [correctionReason, setCorrectionReason] = useState('');
  const [flagReason, setFlagReason] = useState('');
  const [showFlagForm, setShowFlagForm] = useState(false);

  const badge: TrustBadgeType =
    item.review_status === 'APPROVED' ? 'VERIFIED' :
    item.review_status === 'CORRECTED' ? 'CORRECTED' :
    item.review_status === 'FLAGGED' ? 'FLAGGED' :
    item.ai_confidence < 0.7 ? 'LOW_CONFIDENCE' : 'AI_EXTRACTED';

  const handleApprove = () => actions.approve(item.review_id, item.version_number);
  const handleCorrect = () => {
    if (correctedValue.trim()) {
      actions.correct(item.review_id, item.version_number, correctedValue, correctionReason);
      setCorrecting(false);
    }
  };
  const handleFlag = () => {
    if (flagReason.trim()) {
      actions.flag(item.review_id, item.version_number, flagReason);
      setShowFlagForm(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-gray-400 hover:text-gray-700">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <h3 className="text-lg font-semibold text-gray-900">{item.field_name}</h3>
        <TrustBadge type={badge} size="sm" />
      </div>

      {/* Conflict warning */}
      {actions.conflict && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-md p-3 text-sm text-yellow-800">
          Version conflict: this item was modified by another user. Please refresh.
        </div>
      )}

      {/* Value display */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gray-50 rounded-lg p-3">
          <label className="text-xs text-gray-500 uppercase">AI Extracted Value</label>
          <p className="text-sm text-gray-800 mt-1">{item.ai_extracted_value ?? '—'}</p>
        </div>
        {item.human_corrected_value && (
          <div className="bg-blue-50 rounded-lg p-3">
            <label className="text-xs text-blue-500 uppercase">Corrected Value</label>
            <p className="text-sm text-blue-800 mt-1">{item.human_corrected_value}</p>
          </div>
        )}
      </div>

      {/* Confidence */}
      <ConfidenceExplainer overall={item.ai_confidence} />

      {/* Citation */}
      {item.source_citation && (
        <div className="bg-amber-50 border-l-2 border-amber-300 px-3 py-2">
          <label className="text-xs text-amber-600 uppercase">Source Citation</label>
          <p className="text-sm text-gray-700 mt-1 italic">"{item.source_citation}"</p>
        </div>
      )}

      {/* Metadata */}
      <div className="text-xs text-gray-400 space-y-1">
        <p>Field class: {item.field_class} &middot; Version: {item.version_number}</p>
        {item.reviewed_by && <p>Reviewed by: {item.reviewed_by} at {item.reviewed_at}</p>}
      </div>

      {/* Action buttons */}
      {item.review_status === 'PENDING' || item.review_status === 'IN_REVIEW' ? (
        <div className="flex gap-2 pt-2 border-t">
          <button
            onClick={handleApprove}
            disabled={actions.loading === item.review_id}
            className="flex items-center gap-1 px-4 py-2 bg-green-600 text-white text-sm rounded-md hover:bg-green-700 disabled:opacity-50"
          >
            <Check className="w-4 h-4" /> Approve
          </button>
          <button
            onClick={() => setCorrecting(true)}
            className="flex items-center gap-1 px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
          >
            <Pencil className="w-4 h-4" /> Correct
          </button>
          <button
            onClick={() => setShowFlagForm(true)}
            className="flex items-center gap-1 px-4 py-2 bg-red-600 text-white text-sm rounded-md hover:bg-red-700"
          >
            <Flag className="w-4 h-4" /> Flag
          </button>
        </div>
      ) : null}

      {/* Correct form */}
      {correcting && (
        <div className="border rounded-md p-3 space-y-2">
          <input
            type="text"
            placeholder="Corrected value"
            value={correctedValue}
            onChange={(e) => setCorrectedValue(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md"
          />
          <input
            type="text"
            placeholder="Reason for correction"
            value={correctionReason}
            onChange={(e) => setCorrectionReason(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md"
          />
          <div className="flex gap-2">
            <button onClick={handleCorrect} className="px-3 py-1 bg-blue-600 text-white text-sm rounded-md">Save</button>
            <button onClick={() => setCorrecting(false)} className="px-3 py-1 border text-sm rounded-md">Cancel</button>
          </div>
        </div>
      )}

      {/* Flag form */}
      {showFlagForm && (
        <div className="border rounded-md p-3 space-y-2">
          <input
            type="text"
            placeholder="Reason for flagging"
            value={flagReason}
            onChange={(e) => setFlagReason(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md"
          />
          <div className="flex gap-2">
            <button onClick={handleFlag} className="px-3 py-1 bg-red-600 text-white text-sm rounded-md">Flag</button>
            <button onClick={() => setShowFlagForm(false)} className="px-3 py-1 border text-sm rounded-md">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
