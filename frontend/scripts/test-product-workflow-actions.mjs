import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import * as productApi from '../src/api/index.ts';
import { PRODUCT_WORKFLOW_ACTIONS } from '../src/workflow/productWorkflowActions.generated.ts';

const registryUrl = new URL('../src/workflow/productWorkflowActionRegistry.ts', import.meta.url);
assert.ok(existsSync(fileURLToPath(registryUrl)), 'workflow action registry must exist');

const {
  EXPECTED_PRODUCT_WORKFLOW_API_CLIENTS,
  PRODUCT_WORKFLOW_API_CLIENT_BINDINGS,
  dispatchProductWorkflowAction,
  getProductWorkflowAction,
  productWorkflowActionDiagnostic,
} = await import(registryUrl.href);

let calls = 0;
const unknown = await dispatchProductWorkflowAction('unknown_server_action', {
  productId: 42,
  apiClientOverrides: {
    retryStep: () => { calls += 1; },
  },
});
assert.equal(unknown.status, 'unknown');
assert.equal(calls, 0, 'unknown workflow action must not execute any handler');
assert.equal(getProductWorkflowAction('unknown_server_action'), null);
assert.match(productWorkflowActionDiagnostic('unknown_server_action'), /unknown_server_action/);

const known = await dispatchProductWorkflowAction('open_detail', {
  productId: 42,
  navigate: (target) => {
    assert.equal(target, '/products/42');
    calls += 1;
  },
});
assert.equal(known.status, 'handled');
assert.equal(calls, 1);

const missingHandler = await dispatchProductWorkflowAction('open_task_center', { productId: 42 });
assert.equal(missingHandler.status, 'unavailable');
assert.equal(calls, 1, 'known action without a page handler must not execute another action');

const apiDefinitions = PRODUCT_WORKFLOW_ACTIONS.filter((definition) => definition.kind === 'api');
assert.deepEqual(
  Object.keys(EXPECTED_PRODUCT_WORKFLOW_API_CLIENTS).sort(),
  apiDefinitions.map((definition) => definition.action).sort(),
  'every manifest API action must have an independent expected client binding',
);
assert.deepEqual(
  Object.keys(PRODUCT_WORKFLOW_API_CLIENT_BINDINGS).sort(),
  [...new Set(apiDefinitions.map((definition) => definition.client_export))].sort(),
  'API client bindings must exactly cover manifest client_export values',
);
for (const definition of apiDefinitions) {
  const expectedClient = EXPECTED_PRODUCT_WORKFLOW_API_CLIENTS[definition.action];
  assert.equal(definition.client_export, expectedClient, `wrong client_export for ${definition.action}`);
  const binding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS[definition.client_export];
  assert.ok(binding, `missing executable API binding for ${definition.client_export}`);
  assert.equal(binding.execute, productApi[definition.client_export], `binding is not the real API export: ${definition.client_export}`);
  assert.equal(binding.method, definition.method, `wrong method for ${definition.action}`);
  assert.equal(binding.route, definition.route, `wrong route for ${definition.action}`);
}

let apiProductId = null;
const apiResult = await dispatchProductWorkflowAction('retry_auto_image_selection', {
  productId: 77,
  apiClientOverrides: {
    retryProductAutoImageSelection: (productId) => { apiProductId = productId; },
  },
});
assert.equal(apiResult.status, 'handled');
assert.equal(apiProductId, 77, 'API dispatch must execute the client selected by definition.client_export');

console.log('Product workflow action dispatcher checks passed');
