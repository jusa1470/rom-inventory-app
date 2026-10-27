let onUnauthorized = null;

export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

const AUTH_PATHS = new Set(['/api/login', '/api/me']);

function errorMessage(data, resp) {
  const detail = data && data.detail;
  if (Array.isArray(detail)) {
    return detail
      .map(e => `${(e.loc || []).filter(p => p !== 'body').join('.')}: ${e.msg}`)
      .join('; ');
  }
  return detail || `HTTP ${resp.status}`;
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resp.status === 401 && onUnauthorized && !AUTH_PATHS.has(path)) onUnauthorized();
    throw Object.assign(new Error(errorMessage(data, resp)), { status: resp.status });
  }
  return data;
}

export const API = {
  get: path => request('GET', path),
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  delete: path => request('DELETE', path),
};