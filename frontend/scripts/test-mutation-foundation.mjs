import assert from 'node:assert/strict';
import { AxiosError } from 'axios';

import api, {
  apiErrorMessage,
  isRemoteReadOnlyError,
  REMOTE_READ_ONLY_MESSAGE,
} from '../src/api/index.ts';
import { mutationInventory } from '../src/api/mutationInventory.generated.ts';
import { runMutationWithUX } from '../src/api/mutationRunner.ts';


const callsiteId = mutationInventory[0]?.id;
assert(callsiteId, 'foundation test requires at least one mutation callsite');

const ownerState = {
  draft: 'keep-draft',
  selection: [11, 12],
};
let loadingClearCount = 0;
let capturedConfig = null;
let remoteError = null;
let capturedMessage = null;
let capturedError = null;

const caught = await runMutationWithUX(
  callsiteId,
  (metadataConfig) => api.post('/foundation-probe', { keep: 'body' }, {
    ...metadataConfig,
    adapter: async (config) => {
      capturedConfig = config;
      remoteError = new AxiosError(
        'Request failed with status code 403',
        'ERR_BAD_REQUEST',
        config,
        {},
        {
          data: { code: 'REMOTE_DEV_READ_ONLY', detail: '当前是远程只读访问' },
          status: 403,
          statusText: 'Forbidden',
          headers: {},
          config,
        },
      );
      throw remoteError;
    },
  }),
  {
    clearLoading: () => {
      loadingClearCount += 1;
    },
    errorFallback: 'foundation fallback',
    onError: (message, error) => {
      capturedMessage = message;
      capturedError = error;
    },
  },
).catch((error) => error);

assert.equal(caught, remoteError, 'runner/interceptor must preserve the original standard 403 error object');
assert.equal(isRemoteReadOnlyError(caught), true);
assert.equal(apiErrorMessage(caught, 'fallback'), REMOTE_READ_ONLY_MESSAGE);
assert.equal(caught.message, REMOTE_READ_ONLY_MESSAGE);
assert.equal(capturedMessage, REMOTE_READ_ONLY_MESSAGE);
assert.equal(capturedError, remoteError, 'runner onError must receive the original error object');
assert.equal(loadingClearCount, 1, 'registered loading clear must run in finally');
assert.deepEqual(ownerState, { draft: 'keep-draft', selection: [11, 12] });

assert.equal(capturedConfig.fbmMutationCallsiteId, callsiteId);
assert.equal(capturedConfig.headers?.fbmMutationCallsiteId, undefined);
assert.equal(capturedConfig.params?.fbmMutationCallsiteId, undefined);
assert.equal(String(capturedConfig.data).includes('fbmMutationCallsiteId'), false);
assert.equal(String(capturedConfig.url).includes('fbmMutationCallsiteId'), false);

assert.equal(isRemoteReadOnlyError(new Error('ordinary error')), false);
assert.equal(apiErrorMessage({ unexpected: true }, 'fallback-message'), 'fallback-message');
assert.equal(apiErrorMessage(new Error('ordinary error'), 'fallback-message'), 'ordinary error');

let successFinallyCount = 0;
const success = await runMutationWithUX(
  callsiteId,
  async (metadataConfig) => {
    assert.equal(metadataConfig.fbmMutationCallsiteId, callsiteId);
    return 'ok';
  },
  {
    clearLoading: () => { successFinallyCount += 1; },
    errorFallback: 'unused success fallback',
    onError: () => { throw new Error('success path must not call onError'); },
  },
);
assert.equal(success, 'ok');
assert.equal(successFinallyCount, 1);

console.log('Mutation API error and runner foundation checks passed');
