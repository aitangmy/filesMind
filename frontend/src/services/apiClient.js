import { getBackendBaseUrl, getDesktopAuthToken } from './runtimeConfig';

const stripApiProxyPrefix = (path) => {
  const text = String(path || '').trim();
  if (!text.startsWith('/api/')) return text;
  return text.slice(4);
};

export const getApiAuthToken = () => getDesktopAuthToken();

export const buildApiUrl = (path) => {
  const rawPath = String(path || '').trim();
  if (!rawPath) return rawPath;
  if (/^[a-zA-Z][a-zA-Z\d+\-.]*:/.test(rawPath) || rawPath.startsWith('//')) {
    return rawPath;
  }
  const baseUrl = getBackendBaseUrl();
  if (!baseUrl) return rawPath;
  const normalizedPath = stripApiProxyPrefix(rawPath);
  return `${baseUrl}${normalizedPath}`;
};

const withAuthHeaders = (init = {}) => {
  const token = getDesktopAuthToken();
  if (!token) return init;

  const headers = new Headers(init.headers || {});
  if (!headers.has('X-FilesMind-Token')) {
    headers.set('X-FilesMind-Token', token);
  }
  return {
    ...init,
    headers
  };
};

export const apiFetch = (path, init = {}) => {
  return fetch(buildApiUrl(path), withAuthHeaders(init));
};
