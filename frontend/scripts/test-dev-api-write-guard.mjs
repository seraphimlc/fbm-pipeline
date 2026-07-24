import assert from 'node:assert/strict';

const {
  createDevApiWriteGuard,
  isLoopbackAddress,
  normalizeRemoteAddress,
} = await import('../dev-api-write-guard.ts');

assert.equal(normalizeRemoteAddress('127.0.0.42'), '127.0.0.42');
assert.equal(normalizeRemoteAddress('::ffff:127.0.0.9'), '127.0.0.9');
assert.equal(normalizeRemoteAddress('[::1]'), '::1');
assert.equal(normalizeRemoteAddress('[2001:db8::7]'), '2001:db8::7');
assert.equal(isLoopbackAddress('127.255.1.2'), true);
assert.equal(isLoopbackAddress('::ffff:127.0.0.9'), true);
assert.equal(isLoopbackAddress('[::1]'), true);
assert.equal(isLoopbackAddress('2001:db8::7'), false);

function invokeGuard({ address, configuredToken = 'guard-secret', headers = {}, method = 'POST' }) {
  const request = {
    headers: { ...headers },
    method,
    socket: { remoteAddress: address },
  };
  let nextCalls = 0;
  let responseBody = '';
  const responseHeaders = {};
  const response = {
    statusCode: 200,
    setHeader(name, value) {
      responseHeaders[name.toLowerCase()] = String(value);
    },
    end(body = '') {
      responseBody = String(body);
    },
  };
  createDevApiWriteGuard(configuredToken)(request, response, () => {
    nextCalls += 1;
  });
  return { nextCalls, request, responseBody, responseHeaders, statusCode: response.statusCode };
}

const safeRemote = invokeGuard({ address: '2001:db8::7', method: 'GET' });
assert.equal(safeRemote.nextCalls, 1);

const localWrite = invokeGuard({ address: '::ffff:127.0.0.1' });
assert.equal(localWrite.nextCalls, 1);
assert.equal(localWrite.request.headers['x-fbm-proxy-client'], undefined);

const headerAuthorized = invokeGuard({
  address: '2001:db8::7',
  headers: { 'x-fbm-dev-token': 'guard-secret' },
});
assert.equal(headerAuthorized.nextCalls, 1);
assert.equal(headerAuthorized.request.headers['x-fbm-dev-token'], 'guard-secret');
assert.equal(headerAuthorized.request.headers['x-fbm-proxy-client'], 'remote');

const bearerAuthorized = invokeGuard({
  address: '2001:db8::7',
  headers: { authorization: 'Bearer guard-secret' },
});
assert.equal(bearerAuthorized.nextCalls, 1);
assert.equal(bearerAuthorized.request.headers.authorization, 'Bearer guard-secret');
assert.equal(bearerAuthorized.request.headers['x-fbm-proxy-client'], 'remote');

const headerPrecedesWrongBearer = invokeGuard({
  address: '2001:db8::7',
  headers: {
    authorization: 'Bearer wrong',
    'x-fbm-dev-token': 'guard-secret',
  },
});
assert.equal(headerPrecedesWrongBearer.nextCalls, 1);

const emptyHeaderFallsBackToBearer = invokeGuard({
  address: '2001:db8::7',
  headers: {
    authorization: 'Bearer guard-secret',
    'x-fbm-dev-token': '   ',
  },
});
assert.equal(emptyHeaderFallsBackToBearer.nextCalls, 1);

for (const denied of (
  [
    invokeGuard({ address: '2001:db8::7', headers: { 'x-forwarded-for': '127.0.0.1' } }),
    invokeGuard({ address: '2001:db8::7', headers: { 'x-fbm-dev-token': '' } }),
    invokeGuard({ address: '2001:db8::7', headers: { 'x-fbm-dev-token': 'wrong' } }),
    invokeGuard({
      address: '2001:db8::7',
      headers: {
        authorization: 'Bearer guard-secret',
        'x-fbm-dev-token': 'wrong',
      },
    }),
    invokeGuard({ address: '2001:db8::7', configuredToken: '', headers: { 'x-fbm-dev-token': 'anything' } }),
  ]
)) {
  assert.equal(denied.nextCalls, 0);
  assert.equal(denied.statusCode, 403);
  assert.equal(denied.responseHeaders['content-type'], 'application/json; charset=utf-8');
  assert.deepEqual(JSON.parse(denied.responseBody), {
    code: 'REMOTE_DEV_READ_ONLY',
    detail: '当前是远程只读访问',
  });
}

console.log('Dev API write guard unit checks passed');
