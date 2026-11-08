import React, { useState } from 'react';
import { api, ApiError } from '../../api/client.ts';
import { ConnectionCreate, ConnectionResponse } from '../../api/generated/schema.ts';

interface ConnectionFormProps {
  onSuccess: (conn: ConnectionResponse) => void;
  onCancel?: () => void;
  connection?: ConnectionResponse | null;
}

export function ConnectionForm({ onSuccess, onCancel, connection }: ConnectionFormProps): React.JSX.Element {
  const [name, setName] = useState(connection?.name || '');
  const [engine, setEngine] = useState<'postgresql' | 'mysql'>(connection?.engine || 'postgresql');
  const [host, setHost] = useState(connection?.host || '');
  const [port, setPort] = useState<number>(connection?.port || 5432);
  const [database, setDatabase] = useState(connection?.database || '');
  const [username, setUsername] = useState(connection?.username || '');
  const [password, setPassword] = useState('');
  const [caCert, setCaCert] = useState<string | null>(null);
  const [tlsEnabled, setTlsEnabled] = useState(connection?.tls_enabled ?? true);
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
        ...(caCert !== null ? { ca_cert: caCert } : {}),
      };

      const res = connection
        ? await api.patch<ConnectionResponse>(`/api/v1/connections/${connection.id}`, {
            name, host, port: Number(port), database, username, tls_enabled: tlsEnabled,
            ...(caCert !== null ? { ca_cert: caCert } : {}),
            ...(password ? { password } : {}),
          })
        : await api.post<ConnectionResponse>('/api/v1/connections', payload);
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
      <h3 className="text-lg font-bold text-slate-900 mb-4">{connection ? 'Edit Database Connection' : 'Add Database Connection'}</h3>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <label className="block text-sm font-medium">Custom CA certificate (optional)
          <textarea aria-label="Custom CA certificate" value={caCert ?? ''} onChange={(event) => setCaCert(event.target.value)}
            placeholder={connection ? 'Leave untouched to retain the current CA; enter a replacement PEM certificate' : 'PEM certificate; leave empty for public certificate authorities'}
            className="mt-1 w-full border rounded p-2 font-mono text-xs" />
        </label>
        <div>
          <label htmlFor="conn-name" className="block text-sm font-medium text-slate-700 mb-1">
            Connection Name
          </label>
          <input
            id="conn-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Production Analytics"
            className="w-full px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="conn-engine" className="block text-sm font-medium text-slate-700 mb-1">
              Database Engine
            </label>
            <select
              id="conn-engine"
              value={engine}
              disabled={Boolean(connection)}
              onChange={handleEngineChange}
              className="w-full px-3 py-2 border rounded-md text-sm bg-white"
            >
              <option value="postgresql">PostgreSQL (16, 17, 18)</option>
              <option value="mysql">Oracle MySQL (8.0, 8.4)</option>
            </select>
          </div>
          <div>
            <label htmlFor="conn-port" className="block text-sm font-medium text-slate-700 mb-1">
              Port
            </label>
            <input
              id="conn-port"
              type="number"
              required
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              className="w-full px-3 py-2 border rounded-md text-sm"
            />
          </div>
        </div>

        <div>
          <label htmlFor="conn-host" className="block text-sm font-medium text-slate-700 mb-1">
            Hostname
          </label>
          <input
            id="conn-host"
            type="text"
            required
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="pg.internal or db.aivencloud.com"
            className="w-full px-3 py-2 border rounded-md text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="conn-database" className="block text-sm font-medium text-slate-700 mb-1">
              Database Name
            </label>
            <input
              id="conn-database"
              type="text"
              required
              value={database}
              onChange={(e) => setDatabase(e.target.value)}
              className="w-full px-3 py-2 border rounded-md text-sm"
            />
          </div>
          <div>
            <label htmlFor="conn-username" className="block text-sm font-medium text-slate-700 mb-1">
              Username
            </label>
            <input
              id="conn-username"
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 border rounded-md text-sm"
            />
          </div>
        </div>

        <div>
          <label htmlFor="conn-password" className="block text-sm font-medium text-slate-700 mb-1">
            Password
          </label>
          <input
            id="conn-password"
            type="password"
            required={!connection}
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
            Enable TLS / SSL Verification
          </label>
        </div>

        <div className="flex justify-end space-x-3 pt-4 border-t">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              disabled={loading}
              className="px-4 py-2 border rounded-md text-sm text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
          )}
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
