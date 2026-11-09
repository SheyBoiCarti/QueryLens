/**
 * QueryLens Frontend API Client (Contracts C01, C02).
 * Sends relative requests without session credentials.
 */

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

  if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const fetchPromise = fetch(path, {
    ...options,
    headers,
    credentials: 'omit',
  });

  const response = await fetchPromise;

  const requestId = response.headers.get('X-Request-ID') || '';

  if (!response.ok) {
    let errorCode = 'HTTP_ERROR';
    let errorMessage = `HTTP ${response.status}: ${response.statusText}`;

    try {
      const errorJson: unknown = await response.json();
      if (errorJson && typeof errorJson === 'object') {
        const body = errorJson as { error?: { code?: string; message?: string }; detail?: unknown };
        if (body.error) {
          errorCode = body.error.code || errorCode;
          errorMessage = body.error.message || errorMessage;
        } else if (body.detail !== undefined) {
          if (body.detail && typeof body.detail === 'object') {
            const detail = body.detail as { error_code?: string; message?: string };
            errorCode = detail.error_code || errorCode;
            errorMessage = detail.message || JSON.stringify(body.detail);
          } else {
            errorMessage = String(body.detail);
          }
        }
      }
    } catch {
      // Non-JSON response
    }

    throw new ApiError(errorCode, errorMessage, requestId, response.status);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
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
