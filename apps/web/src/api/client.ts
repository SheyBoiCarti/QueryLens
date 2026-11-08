/**
 * QueryLens Frontend API Client (Contracts C01, C02).
 * Handles relative requests, CSRF synchronizer tokens in memory, and cookie credentials.
 */

import {
  CsrfResponse,
  LoginRequest,
  LoginResponse,
  StatusResponse,
  UserResponse,
  ErrorEnvelope,
} from './generated/schema.ts';

let _csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  _csrfToken = token;
}

export function getCsrfToken(): string | null {
  return _csrfToken;
}

export class ApiError extends Error {
  code: string;
  requestId: string;
  statusCode: number;

  constructor(code: string, message: string, requestId: string, statusCode: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.requestId = requestId;
    this.statusCode = statusCode;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('X-QueryLens-Client', 'web');

  if (_csrfToken && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(options.method?.toUpperCase() || '')) {
    headers.set('X-CSRF-Token', _csrfToken);
  }

  if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const fetchPromise = fetch(path, {
    ...options,
    headers,
    credentials: 'include', // send cookies
  });

  const response = await fetchPromise;

  const requestId = response.headers.get('X-Request-ID') || '';

  if (!response.ok) {
    let errorCode = 'HTTP_ERROR';
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`;

    try {
      const errorJson = (await response.json()) as ErrorEnvelope;
      if (errorJson?.error) {
        errorCode = errorJson.error.code;
        errorMessage = errorJson.error.message;
      }
    } catch {
      // Non-JSON response
    }

    if (response.status === 401 && !path.endsWith('/auth/login')) {
      setCsrfToken(null);
      window.dispatchEvent(new Event('querylens:unauthorized'));
    }
    throw new ApiError(errorCode, errorMessage, requestId, response.status);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  login: async (creds: LoginRequest): Promise<LoginResponse> => {
    const res = await request<LoginResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(creds),
    });
    setCsrfToken(res.csrf_token);
    return res;
  },

  logout: async (): Promise<StatusResponse> => {
    const res = await request<StatusResponse>('/api/v1/auth/logout', {
      method: 'POST',
    });
    setCsrfToken(null);
    return res;
  },

  getMe: async (options: RequestInit = {}): Promise<UserResponse> => {
    return request<UserResponse>('/api/v1/auth/me', options);
  },

  getCsrf: async (options: RequestInit = {}): Promise<CsrfResponse> => {
    const res = await request<CsrfResponse>('/api/v1/auth/csrf', options);
    setCsrfToken(res.csrf_token);
    return res;
  },

  get: async <T>(path: string, options: RequestInit = {}): Promise<T> => {
    return request<T>(path, { ...options, method: 'GET' });
  },

  post: async <T>(path: string, body?: unknown): Promise<T> => {
    return request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  patch: async <T>(path: string, body: unknown): Promise<T> => {
    return request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
  },

  put: async <T>(path: string, body: unknown): Promise<T> => {
    return request<T>(path, { method: 'PUT', body: JSON.stringify(body) });
  },

  delete: async <T>(path: string): Promise<T> => {
    return request<T>(path, { method: 'DELETE' });
  },
};
