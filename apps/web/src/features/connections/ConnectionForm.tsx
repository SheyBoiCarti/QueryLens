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
    <div className="card max-w-xl">
      <h2 className="section-title mb-4">{connection ? 'Edit database connection' : 'Add database connection'}</h2>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-surface text-danger text-sm rounded border border-danger-border">
          {error}
        </div>
      )}

      {!connection && <p className="mb-4 text-sm text-muted">Saving verifies your connection and imports accessible tables and columns automatically. You can adjust table access afterward.</p>}
      <form onSubmit={handleSubmit}>
        <fieldset disabled={loading} className="space-y-4">
        <div className="rounded border border-border p-3 space-y-2">
          <label htmlFor="connection-link" className="block font-medium">Connection link</label>
          <input id="connection-link" type="password" autoComplete="off" value={connectionString}
            onChange={(event) => setConnectionString(event.target.value)}
            placeholder="Paste the connection link from your database provider"
            className="w-full border rounded" />
          <button type="button" className="text-accent btn-link" onClick={() => {
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
          <p className="text-xs text-muted">Fills in your details and uses the encryption setting in the link.</p>
        </div>
        <div>
          <label htmlFor="conn-name" className="block font-medium mb-1">
            Connection name
          </label>
          <input
            id="conn-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Production Analytics"
            className="w-full border rounded-md"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="conn-engine" className="block font-medium mb-1">
              Database engine
            </label>
            <select
              id="conn-engine"
              value={engine}
              disabled={Boolean(connection)}
              onChange={handleEngineChange}
              className="w-full border rounded-md"
            >
              <option value="postgresql">PostgreSQL (16, 17, 18)</option>
              <option value="mysql">Oracle MySQL (8.0, 8.4)</option>
            </select>
          </div>
          <div>
            <label htmlFor="conn-port" className="block font-medium mb-1">
              Port
            </label>
            <input
              id="conn-port"
              type="number"
              required
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              className="w-full border rounded-md"
            />
          </div>
        </div>

        <div>
          <label htmlFor="conn-host" className="block font-medium mb-1">
            Hostname
          </label>
          <input
            id="conn-host"
            type="text"
            required
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="pg.internal or db.aivencloud.com"
            className="w-full border rounded-md"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="conn-database" className="block font-medium mb-1">
              Database name
            </label>
            <input
              id="conn-database"
              type="text"
              required
              value={database}
              onChange={(e) => setDatabase(e.target.value)}
              className="w-full border rounded-md"
            />
          </div>
          <div>
            <label htmlFor="conn-username" className="block font-medium mb-1">
              Username
            </label>
            <input
              id="conn-username"
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full border rounded-md"
            />
          </div>
        </div>

        <div>
          <label htmlFor="conn-password" className="block font-medium mb-1">
            Password
          </label>
          <input
            id="conn-password"
            type="password"
            required={!connection}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border rounded-md"
          />
        </div>

        <div className="flex items-center space-x-2">
          <input
            type="checkbox"
            id="tls-checkbox"
            checked={tlsEnabled}
            onChange={(e) => setTlsEnabled(e.target.checked)}
            className="rounded text-accent"
          />
          <label htmlFor="tls-checkbox" className="font-medium">
            Encrypt connection
          </label>
        </div>

        {tlsEnabled && <div className="space-y-2">
          <label htmlFor="connection-security" className="block font-medium">Connection security</label>
          <select id="connection-security" value={tlsMode}
            onChange={(event) => setTlsMode(event.target.value as typeof tlsMode)} className="w-full border rounded">
            <option value="verify-full">Encrypt and verify server identity (recommended)</option>
            <option value="verify-ca">Encrypt and verify provider certificate</option>
            <option value="require">Encrypt using provider's required mode</option>
          </select>
          {tlsMode === 'require' ? <p className="text-xs text-muted">
            Matches require / REQUIRED in your provider's link. Data is encrypted; the server's identity is not verified.
          </p> : <>
            <label htmlFor="certificate-file" className="block font-medium">Provider certificate (if needed)</label>
            <p className="text-xs text-muted">Most providers need no extra file. For Aiven, download ca.pem from your service Overview page and select it here.</p>
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
            {certificateName && <p role="status" className="text-xs text-muted">Certificate selected: {certificateName}</p>}
            <details><summary className="text-sm cursor-pointer">Paste a certificate instead</summary>
              <label className="block">Custom CA certificate
                <textarea aria-label="Custom CA certificate" value={caCert ?? ''} onChange={(event) => setCaCert(event.target.value)}
                  placeholder={connection ? 'Leave untouched to keep your saved certificate' : 'Paste your provider certificate'}
                  className="mt-1 w-full border rounded font-mono" />
              </label>
            </details>
          </>}
        </div>}

        {loading && <p role="status" className="text-sm text-muted">{connection ? 'Saving your connection settings…' : 'Connecting to your database and importing its schema. Please keep this page open; this can take a moment.'}</p>}
        <div className="flex justify-end space-x-3 pt-4 border-t">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              disabled={loading}
              className="border rounded-md text-text"
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            disabled={loading}
            className="rounded-md btn-primary"
          >
            {loading ? (connection ? 'Saving...' : 'Connecting and importing...') : 'Save connection'}
          </button>
        </div>
        </fieldset>
      </form>
    </div>
  );
}

export default ConnectionForm;
