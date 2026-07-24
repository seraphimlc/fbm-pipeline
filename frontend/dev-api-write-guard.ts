import { createHash, timingSafeEqual } from 'node:crypto';
import type { IncomingMessage, ServerResponse } from 'node:http';


const SAFE_HTTP_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
const REMOTE_PROXY_HEADER = 'x-fbm-proxy-client';
const STANDARD_DENIAL = {
  code: 'REMOTE_DEV_READ_ONLY',
  detail: '当前是远程只读访问',
};

type NextFunction = (error?: unknown) => void;


function isIpv4Address(value: string): boolean {
  const parts = value.split('.');
  return parts.length === 4 && parts.every((part) => {
    if (!/^\d{1,3}$/.test(part)) return false;
    const number = Number(part);
    return number >= 0 && number <= 255;
  });
}


export function normalizeRemoteAddress(value: string | null | undefined): string {
  let address = String(value || '').trim().toLowerCase();
  if (address.startsWith('[')) {
    const closingBracket = address.indexOf(']');
    if (closingBracket > 0) {
      address = address.slice(1, closingBracket);
    }
  }
  if (address.startsWith('::ffff:')) {
    const mappedAddress = address.slice('::ffff:'.length);
    if (isIpv4Address(mappedAddress)) {
      return mappedAddress;
    }
  }
  return address;
}


export function isLoopbackAddress(value: string | null | undefined): boolean {
  const address = normalizeRemoteAddress(value);
  if (address === '::1' || address === '0:0:0:0:0:0:0:1' || address === 'localhost') {
    return true;
  }
  return isIpv4Address(address) && address.split('.')[0] === '127';
}


function firstHeaderValue(value: string | string[] | undefined): string {
  return String(Array.isArray(value) ? value[0] || '' : value || '').trim();
}


function requestToken(request: IncomingMessage): string {
  const headerToken = firstHeaderValue(request.headers['x-fbm-dev-token']);
  if (headerToken) {
    return headerToken;
  }
  const authorization = firstHeaderValue(request.headers.authorization);
  return authorization.startsWith('Bearer ')
    ? authorization.slice('Bearer '.length).trim()
    : '';
}


function tokensMatch(providedToken: string, configuredToken: string): boolean {
  if (!providedToken || !configuredToken) {
    return false;
  }
  const providedDigest = createHash('sha256').update(providedToken, 'utf8').digest();
  const configuredDigest = createHash('sha256').update(configuredToken, 'utf8').digest();
  const digestMatches = timingSafeEqual(providedDigest, configuredDigest);
  return digestMatches && Buffer.byteLength(providedToken, 'utf8') === Buffer.byteLength(configuredToken, 'utf8');
}


function rejectRemoteWrite(response: ServerResponse): void {
  const body = JSON.stringify(STANDARD_DENIAL);
  response.statusCode = 403;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Content-Length', Buffer.byteLength(body, 'utf8'));
  response.end(body);
}


export function createDevApiWriteGuard(configuredToken: string | undefined) {
  const expectedToken = String(configuredToken || '').trim();
  return (request: IncomingMessage, response: ServerResponse, next: NextFunction): void => {
    const method = String(request.method || 'GET').toUpperCase();
    if (SAFE_HTTP_METHODS.has(method) || isLoopbackAddress(request.socket.remoteAddress)) {
      next();
      return;
    }
    if (!tokensMatch(requestToken(request), expectedToken)) {
      rejectRemoteWrite(response);
      return;
    }
    request.headers[REMOTE_PROXY_HEADER] = 'remote';
    next();
  };
}
