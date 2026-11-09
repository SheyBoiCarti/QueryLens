import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { parseConnectionString } from '../features/connections/connectionString.ts';
import ConnectionForm from '../features/connections/ConnectionForm.tsx';
import { api } from '../api/client.ts';

vi.mock('../api/client.ts', () => ({ api: { post: vi.fn(), patch: vi.fn() }, ApiError: class extends Error {} }));

beforeEach(() => { vi.clearAllMocks(); });

describe('provider connection links', () => {
  it.each([
    ['mysql://reader:p%40ss@db.example.com:28173/defaultdb?ssl-mode=REQUIRED', 'mysql', 'require'],
    ['postgres://reader:pass@db.example.com:28173/defaultdb?sslmode=require', 'postgresql', 'require'],
    ['postgresql://reader:pass@db.example.com/db?sslmode=verify-full', 'postgresql', 'verify-full'],
    ['mysql://reader:pass@db.example.com/db?ssl-mode=VERIFY_IDENTITY', 'mysql', 'verify-full'],
    ['postgres://reader:pass@db.example.com/db', 'postgresql', 'verify-full'],
  ])('imports %s', (link, engine, mode) => {
    expect(parseConnectionString(link)).toMatchObject({ engine, tls_enabled: true, tls_mode: mode });
  });

  it('decodes credentials and defaults the port', () => {
    expect(parseConnectionString('mysql://read%40only:p%40ss%3Aword@db.example.com/my%20db'))
      .toMatchObject({ username: 'read@only', password: 'p@ss:word', port: 3306, database: 'my db' });
  });

  it.each(['sslmode=prefer', 'sslmode=require&sslmode=disable', 'sslrootcert=/local/ca.pem', 'options=anything'])('rejects unsupported options without exposing passwords: %s', (option) => {
    expect(() => parseConnectionString(`postgres://reader:secret@db.example.com/db?${option}`)).toThrow(/cannot import/);
    try { parseConnectionString(`postgres://reader:secret@db.example.com/db?${option}`); }
    catch (error) { expect(String(error)).not.toContain('secret'); }
  });

  it('imports and saves the selected mode without sending a raw connection URL', async () => {
    vi.mocked(api.post).mockResolvedValue({ id: 'saved' });
    render(<ConnectionForm onSuccess={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Connection link'), { target: { value: 'postgres://reader:pass@db.example.com:28173/defaultdb?sslmode=require' } });
    fireEvent.click(screen.getByText('Use connection link'));
    expect(screen.getByLabelText('Connection link')).toHaveValue('');
    expect(screen.getByLabelText('Connection security')).toHaveValue('require');
    fireEvent.change(screen.getByLabelText('Connection Name'), { target: { value: 'My database' } });
    fireEvent.click(screen.getByText('Save Connection'));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/v1/connections', expect.objectContaining({
      host: 'db.example.com', port: 28173, password: 'pass', tls_enabled: true, tls_mode: 'require',
    })));
    expect(vi.mocked(api.post).mock.calls[0][1]).not.toHaveProperty('connection_string');
  });
});

it('reads a provider certificate file and includes it when saving', async () => {
  vi.mocked(api.post).mockResolvedValue({ id: 'saved' });
  render(<ConnectionForm onSuccess={vi.fn()} />);
  const contents = '-----BEGIN CERTIFICATE-----\nprovider-ca\n-----END CERTIFICATE-----';
  const file = new File([contents], 'ca.pem', { type: 'text/plain' });
  Object.defineProperty(file, 'text', { value: () => Promise.resolve(contents) });
  fireEvent.change(screen.getByLabelText('Provider certificate (if needed)'), { target: { files: [file] } });
  await screen.findByText('Certificate selected: ca.pem');
  fireEvent.change(screen.getByLabelText('Connection link'), { target: { value: 'postgres://reader:pass@db.example.com/db?sslmode=verify-full' } });
  fireEvent.click(screen.getByText('Use connection link'));
  fireEvent.change(screen.getByLabelText('Connection Name'), { target: { value: 'Verified DB' } });
  fireEvent.click(screen.getByText('Save Connection'));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/v1/connections', expect.objectContaining({ ca_cert: contents, tls_mode: 'verify-full' })));
});

it('rejects private key uploads', async () => {
  render(<ConnectionForm onSuccess={vi.fn()} />);
  const file = new File(['private-key'], 'private.pem');
  Object.defineProperty(file, 'text', { value: () => Promise.resolve('-----BEGIN PRIVATE KEY-----') });
  fireEvent.change(screen.getByLabelText('Provider certificate (if needed)'), { target: { files: [file] } });
  expect(await screen.findByRole('alert')).toHaveTextContent('Choose the CA certificate');
  expect(api.post).not.toHaveBeenCalled();
});
