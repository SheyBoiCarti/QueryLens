import React, { useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionCreate, ConnectionResponse } from '../../api/generated/schema.ts';

interface ConnectionFormProps {
  onSuccess: (conn: ConnectionResponse) => void;
  onCancel: () => void;
}

export function ConnectionForm({ onSuccess, onCancel }: ConnectionFormProps): React.JSX.Element {
  const [name, setName] = useState('');
  const [engine, setEngine] = useState<'postgresql' | 'mysql'>('postgresql');
  const [host, setHost] = useState('');
  const [port, setPort] = useState<number>(5432);
  const [database, setDatabase] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tlsEnabled, setTlsEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleEngineChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = e.target.value as 'postgresql' | 'mysql';
    setEngine(selected);
    setPort(selected === 'postgresql' ? 5432 : 3306);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const payload: ConnectionCreate = {
        name,
        engine,
        host,
        port: Number(port),
        database,
        username,
        password,
        tls_enabled: tlsEnabled,
      };

      const res = await api.post<ConnectionResponse>('/api/v1/connections', payload);
      onSuccess(res);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('Failed to create database connection.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow border border-slate-200 p-6 max-w-xl mx-auto">
      <h3 className="text-lg font-bold text-slate-900 mb-4">Add Database Connection</h3>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Connection Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm"
            placeholder="e.g. Analytics PostgreSQL"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Engine</label>
            <select
              value={engine}
              onChange={handleEngineChange}
              className="w-full px-3 py-2 border rounded-md text-sm bg-white"
            >
              <option value="postgresql">PostgreSQL (16, 17, 18)</option>
              <option value="mysql">Oracle MySQL (8.0, 8.4)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Port</label>
            <input
              type="number"
              required
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              className="w-full px-3 py-2 border rounded-md text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Host / Address</label>
          <input
            type="text"
            required
            value={host}
            onChange={(e) => setHost(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm"
            placeholder="pg.internal or db.aivencloud.com"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Database Name</label>
            <input
              type="text"
              required
              value={database}
              onChange={(e) => setDatabase(e.target.value)}
              className="w-full px-3 py-2 border rounded-md text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Username</label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 border rounded-md text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Password</label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 border rounded-md text-sm"
          />
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="tls-checkbox"
            checked={tlsEnabled}
            onChange={(e) => setTlsEnabled(e.target.checked)}
            className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
          />
          <label htmlFor="tls-checkbox" className="text-sm font-medium text-slate-700">
            Enable TLS / SSL Verification (Required for production)
          </label>
        </div>

        <div className="flex justify-end space-x-3 pt-4 border-t">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 border rounded-md text-sm text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? 'Saving...' : 'Save Connection'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default ConnectionForm;
