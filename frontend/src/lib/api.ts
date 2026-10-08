/** HTTP client wrapper with error handling. */
import type { APIResponse } from './types';

class ApiError extends Error {
  constructor(public status: number, message: string, public data?: unknown) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(url: string, options: RequestInit = {}): Promise<APIResponse<T>> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail || res.statusText, body);
  }

  return res.json();
}

export const api = {
  get: <T>(url: string) => request<T>(url),

  post: <T>(url: string, body?: unknown) =>
    request<T>(url, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),

  put: <T>(url: string, body?: unknown) =>
    request<T>(url, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),

  delete: <T>(url: string) => request<T>(url, { method: 'DELETE' }),

  upload: async <T>(url: string, file: File): Promise<APIResponse<T>> => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(url, { method: 'POST', body: form });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body?.detail || res.statusText, body);
    }
    return res.json();
  },
};

export { ApiError };
