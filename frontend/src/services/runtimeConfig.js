const FALLBACK_RUNTIME = {
  backendBaseUrl: '',
  authToken: ''
};

const sanitizeBaseUrl = (value) => {
  const text = String(value || '').trim();
  if (!text) return '';
  return text.replace(/\/+$/, '');
};

export const getRuntimeConfig = () => {
  if (typeof window === 'undefined') {
    return { ...FALLBACK_RUNTIME };
  }
  const raw = window.__FILESMIND_RUNTIME__ || {};
  return {
    backendBaseUrl: sanitizeBaseUrl(raw.backendBaseUrl || raw.baseUrl || ''),
    authToken: String(raw.authToken || '').trim()
  };
};

export const getBackendBaseUrl = () => getRuntimeConfig().backendBaseUrl;

export const getDesktopAuthToken = () => getRuntimeConfig().authToken;
