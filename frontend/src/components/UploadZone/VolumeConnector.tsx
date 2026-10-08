import { useState } from 'react';
import { Database, Link } from 'lucide-react';
import { useSettingsStore } from '@/stores/settingsStore';

export function VolumeConnector() {
  const volumeConnection = useSettingsStore((s) => s.volumeConnection);
  const setVolumeConnection = useSettingsStore((s) => s.setVolumeConnection);

  const [catalog, setCatalog] = useState(volumeConnection?.catalog ?? 'dev');
  const [schema, setSchema] = useState(volumeConnection?.schema ?? 'doc_intel');
  const [volume, setVolume] = useState(volumeConnection?.volume ?? 'prvdr_contracts');

  const handleConnect = () => {
    setVolumeConnection({ catalog, schema, volume });
  };

  const connected = volumeConnection !== null;

  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-2 mb-2">
        <Database className="w-4 h-4 text-gray-500" />
        <span className="text-sm font-medium text-gray-700">Volume Connector</span>
        {connected && (
          <span className="ml-auto inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded-full">
            <Link className="w-3 h-3" /> Connected
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Catalog</label>
          <input
            type="text"
            value={catalog}
            onChange={(e) => setCatalog(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Schema</label>
          <input
            type="text"
            value={schema}
            onChange={(e) => setSchema(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Volume</label>
          <input
            type="text"
            value={volume}
            onChange={(e) => setVolume(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md"
          />
        </div>
      </div>

      <button
        onClick={handleConnect}
        className="w-full px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
      >
        {connected ? 'Update Connection' : 'Connect to Volume'}
      </button>

      {connected && (
        <p className="text-xs text-gray-500">
          /Volumes/{volumeConnection.catalog}/{volumeConnection.schema}/{volumeConnection.volume}/
        </p>
      )}
    </div>
  );
}
