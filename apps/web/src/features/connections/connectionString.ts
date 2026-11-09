import type { ConnectionCreate } from '../../api/generated/schema.ts';

export type ImportedConnection = Pick<ConnectionCreate,
  'engine' | 'host' | 'port' | 'database' | 'username' | 'password' | 'tls_enabled' | 'tls_mode'>;

/** Parse locally: connection URLs (including passwords) never enter browser URLs or logs. */
export function parseConnectionString(value: string): ImportedConnection {
  try {
    const url = new URL(value.trim());
    const engine = url.protocol === 'mysql:' ? 'mysql'
      : ['postgres:', 'postgresql:'].includes(url.protocol) ? 'postgresql' : null;
    if (!engine || !url.hostname || !url.username || !url.password || url.hash) throw new Error();
    const database = decodeURIComponent(url.pathname.slice(1));
    if (!database || database.includes('/')) throw new Error();
    const options = [...url.searchParams.entries()];
    if (options.some(([key]) => !['sslmode', 'ssl-mode', 'ssl'].includes(key.toLowerCase())) || options.length > 1) {
      throw new Error('options');
    }
    const mode = (options[0]?.[1] ?? 'verify-full').toLowerCase().replace(/_/g, '-');
    const modes: Record<string, ImportedConnection['tls_mode'] | 'disable'> = {
      require: 'require', required: 'require', true: 'require',
      'verify-ca': 'verify-ca', 'verify-full': 'verify-full', 'verify-identity': 'verify-full',
      disable: 'disable', disabled: 'disable', false: 'disable',
    };
    const tlsMode = modes[mode];
    if (!tlsMode) throw new Error('options');
    const port = url.port ? Number(url.port) : engine === 'mysql' ? 3306 : 5432;
    if (port < 1 || port > 65535) throw new Error();
    return { engine, host: url.hostname.replace(/^\[|\]$/g, ''), port, database,
      username: decodeURIComponent(url.username), password: decodeURIComponent(url.password),
      tls_enabled: tlsMode !== 'disable', tls_mode: tlsMode === 'disable' ? 'verify-full' : tlsMode };
  } catch (error) {
    // Never echo the URL or a native URL parsing error containing credentials.
    throw new Error(error instanceof Error && error.message === 'options'
      ? 'This link contains connection options we cannot import. Enter the details below and choose the encryption setting recommended by your provider.'
      : 'Enter a MySQL or PostgreSQL connection link with a username, password, hostname and database.');
  }
}
