/**
 * ProvenanceModal — Full evidence chain drilldown for any extracted value.
 *
 * Shows: current state, review history, confidence breakdown, source citation,
 * amendment chain, and source file metadata.
 */
import { FileText, Shield, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { ROUTES } from '../../lib/constants';
import { TrustBadge } from '../TrustBadge/TrustBadge';
import { ConfidenceExplainer } from '../ConfidenceExplainer/ConfidenceExplainer';
import { ProvenanceTimeline } from './ProvenanceTimeline';
import { CitationCard } from './CitationCard';
import { LoadingSpinner } from '../common/LoadingSpinner';

interface ProvenanceModalProps {
  documentVersionId: string;
  fieldName: string;
  isOpen: boolean;
  onClose: () => void;
}

export function ProvenanceModal({ documentVersionId, fieldName, isOpen, onClose }: ProvenanceModalProps) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    setError(null);

    api.get(`${ROUTES.PROVENANCE}/${documentVersionId}/${fieldName}`)
      .then((res) => setData(res.data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [isOpen, documentVersionId, fieldName]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Provenance for ${fieldName}`}
      >
        {/* Header */}
        <div className="sticky top-0 flex items-center justify-between border-b bg-white px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold">Provenance: {fieldName}</h2>
            <p className="text-sm text-gray-500">{documentVersionId.slice(0, 12)}...</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 hover:bg-gray-100" aria-label="Close">
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-6 p-6">
          {loading && <LoadingSpinner size="md" label="Loading provenance..." />}
          {error && <div className="text-sm text-red-600">{error}</div>}

          {data && (
            <>
              {/* Current State */}
              <section>
                <h3 className="mb-2 text-sm font-semibold text-gray-700 uppercase tracking-wide">Current State</h3>
                <div className="rounded-lg border bg-green-50 p-4">
                  <div className="flex items-center gap-3">
                    <span className="text-xl font-bold">{data.current_state?.trusted_value}</span>
                    <TrustBadge type={data.current_state?.review_status?.toLowerCase() || 'ai_extracted'} />
                  </div>
                  <div className="mt-1 text-sm text-gray-600">
                    Confidence: {((data.current_state?.confidence_score || 0) * 100).toFixed(0)}%
                  </div>
                </div>
              </section>

              {/* Review History */}
              {data.review_actions?.length > 0 && (
                <section>
                  <h3 className="mb-2 text-sm font-semibold text-gray-700 uppercase tracking-wide">Review History</h3>
                  <ProvenanceTimeline events={data.review_actions.map((a: any) => ({
                    actionType: a.action_type,
                    previousValue: a.previous_value,
                    newValue: a.new_value,
                    performedBy: a.performed_by,
                    performedAt: a.performed_at,
                  }))} />
                </section>
              )}

              {/* Confidence Breakdown */}
              {data.confidence_explanation && (
                <section>
                  <h3 className="mb-2 text-sm font-semibold text-gray-700 uppercase tracking-wide">Confidence Breakdown</h3>
                  <ConfidenceExplainer
                    overall={data.confidence_explanation.ai_extract_confidence ?? 0}
                    signals={{
                      ai_confidence: data.confidence_explanation.ai_extract_confidence ?? 0,
                      format_valid: data.confidence_explanation.format_validation ?? 0,
                      cross_field_valid: data.confidence_explanation.cross_field_consistency ?? 0,
                      citation_present: data.citations?.length > 0 ? 1 : 0,
                    }}
                  />
                </section>
              )}

              {/* Citations */}
              {data.citations?.length > 0 && (
                <section>
                  <h3 className="mb-2 text-sm font-semibold text-gray-700 uppercase tracking-wide">Source Citations</h3>
                  <div className="space-y-2">
                    {data.citations.map((c: any, i: number) => (
                      <CitationCard
                        key={i}
                        page={c.page}
                        section={c.section}
                        text={c.text}
                        documentName={data.source_file?.file_name}
                      />
                    ))}
                  </div>
                </section>
              )}

              {/* Amendment Chain */}
              {data.amendment_chain?.length > 0 && (
                <section>
                  <h3 className="mb-2 text-sm font-semibold text-gray-700 uppercase tracking-wide">Amendment Chain</h3>
                  <div className="space-y-1">
                    {data.amendment_chain.map((a: any, i: number) => (
                      <div key={i} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                        <Shield size={14} className={a.status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'} />
                        <span className="font-medium">{a.relationship_type}</span>
                        <span className="text-gray-500">|</span>
                        <span className="text-gray-600">{a.document_id?.slice(0, 12)}...</span>
                        <span className={`ml-auto text-xs px-2 py-0.5 rounded-full ${
                          a.status === 'ACTIVE' ? 'bg-green-100 text-green-700' :
                          a.status === 'SUPERSEDED' ? 'bg-gray-100 text-gray-600' :
                          'bg-yellow-100 text-yellow-700'
                        }`}>{a.status}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Source File */}
              {data.source_file && (
                <section>
                  <h3 className="mb-2 text-sm font-semibold text-gray-700 uppercase tracking-wide">Source File</h3>
                  <div className="flex items-center gap-3 rounded-lg border p-3">
                    <FileText size={20} className="text-gray-400" />
                    <div>
                      <div className="font-medium text-sm">{data.source_file.file_name}</div>
                      <div className="text-xs text-gray-500">
                        Uploaded {data.source_file.upload_date}
                        {data.source_file.file_checksum && ` | SHA: ${data.source_file.file_checksum.slice(0, 8)}`}
                      </div>
                    </div>
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
