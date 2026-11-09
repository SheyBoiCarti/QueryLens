import React, { useState } from 'react';
import { parseConnectionString } from './connectionString.ts';
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
  const [connectionString, setConnectionString] = useState('');
  const [tlsMode, setTlsMode] = useState<'require' | 'verify-ca' | 'verify-full'>(connection?.tls_mode ?? 'verify-full');
  const [certificateName, setCertificateName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleEngineChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = e.target.value as 'postgresql' | 'mysql';
    setEngine(selected);
    setPort(selected === 'postgresql' ? 5432 : 3306);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError(null);
    setLoading(true);

    try {
      const payload: ConnectionCreate = {
        import_schema: true,
        name,
        engine,
        host,
        port: Number(port),
        database,
        username,
        password,
        tls_enabled: tlsEnabled,
        tls_mode: tlsMode,
        ...(caCert !== null ? { ca_cert: caCert } : {}),
      };

      const res = connection
        ? await api.patch<ConnectionResponse>(`/api/v1/connections/${connection.id}`, {
            name, host, port: Number(port), database, username, tls_enabled: tlsEnabled, tls_mode: tlsMode,
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

      {!connection && <p className="mb-4 text-sm text-slate-600">Saving verifies your connection and imports accessible tables and columns automatically. You can adjust table access afterward.</p>}
      <form onSubmit={handleSubmit}>
        <fieldset disabled={loading} className="space-y-4">
        <div className="rounded border border-slate-200 p-3 space-y-2">
          <label htmlFor="connection-link" className="block text-sm font-medium">Connection link</label>
          <input id="connection-link" type="password" autoComplete="off" value={connectionString}
            onChange={(event) => setConnectionString(event.target.value)}
            placeholder="Paste the connection link from your database provider"
            className="w-full border rounded p-2 text-sm" />
          <button type="button" className="text-sm text-indigo-700" onClick={() => {
            try {
              const imported = parseConnectionString(connectionString);
              if (connection && imported.engine !== connection.engine) {
                throw new Error('This link uses a different database type. Add a new connection instead.');
              }
              setEngine(imported.engine); setHost(imported.host); setPort(imported.port!);
              setDatabase(imported.database); setUsername(imported.username); setPassword(imported.password!);
              setTlsEnabled(imported.tls_enabled!); setTlsMode(imported.tls_mode!);
              setConnectionString(''); setError(null);
            } catch (err) { setError(err instanceof Error ? err.message : 'Unable to read connection link.'); }
          }}>Use connection link</button>
          <p className="text-xs text-slate-500">Fills in your details and uses the encryption setting in the link.</p>
        </div>
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
            Encrypt connection
          </label>
        </div>

        {tlsEnabled && <div className="space-y-2">
          <label htmlFor="connection-security" className="block text-sm font-medium">Connection security</label>
          <select id="connection-security" value={tlsMode}
            onChange={(event) => setTlsMode(event.target.value as typeof tlsMode)} className="w-full border rounded p-2 text-sm">
            <option value="verify-full">Encrypt and verify server identity (recommended)</option>
            <option value="verify-ca">Encrypt and verify provider certificate</option>
            <option value="require">Encrypt using provider's required mode</option>
          </select>
          {tlsMode === 'require' ? <p className="text-xs text-slate-500">
            Matches require / REQUIRED in your provider's link. Data is encrypted; the server's identity is not verified.
          </p> : <>
            <label htmlFor="certificate-file" className="block text-sm font-medium">Provider certificate (if needed)</label>
            <p className="text-xs text-slate-500">Most providers need no extra file. For Aiven, download ca.pem from your service Overview page and select it here.</p>
            <input id="certificate-file" type="file" accept=".pem,.crt,.cer" onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              try {
                if (file.size > 262144) throw new Error('Choose a certificate file smaller than 256 KB.');
                const contents = await file.text();
                if (!contents.includes('-----BEGIN CERTIFICATE-----') || !contents.includes('-----END CERTIFICATE-----') || contents.includes('PRIVATE KEY')) {
                  throw new Error('Choose the CA certificate downloaded from your provider (a PEM file).');
                }
                setCaCert(contents); setCertificateName(file.name); setError(null);
              } catch (err) { setError(err instanceof Error ? err.message : 'Unable to read certificate file.'); }
            }} />
            {certificateName && <p role="status" className="text-xs text-slate-600">Certificate selected: {certificateName}</p>}
            <details><summary className="text-sm cursor-pointer">Paste a certificate instead</summary>
              <label className="block text-sm">Custom CA certificate
                <textarea aria-label="Custom CA certificate" value={caCert ?? ''} onChange={(event) => setCaCert(event.target.value)}
                  placeholder={connection ? 'Leave untouched to keep your saved certificate' : 'Paste your provider certificate'}
                  className="mt-1 w-full border rounded p-2 font-mono text-xs" />
              </label>
            </details>
          </>}
        </div>}

        {loading && <p role="status" className="text-sm text-slate-600">{connection ? 'Saving your connection settings…' : 'Connecting to your database and importing its schema. Please keep this page open; this can take a moment.'}</p>}
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
            {loading ? (connection ? 'Saving...' : 'Connecting and importing...') : 'Save Connection'}
          </button>
        </div>
        </fieldset>
      </form>
    </div>
  );
}

export default ConnectionForm;
