import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  analyzeMutationInventory,
  generateMutationInventory,
  renderMutationInventory,
} from './generate-mutation-inventory.mjs';


const ownerEntry = `{
  owner_component: 'FixtureOwner',
  owner_state: 'fixture state',
  loading_state: 'fixtureLoading',
  catch_policy: 'D2b pending: preserve owner state and show apiErrorMessage',
  finally_policy: 'D2b pending: clear fixtureLoading',
  playwright_case: 'D2b pending: fixture',
}`;


function renderOwnerContract(ids, entry = ownerEntry) {
  const entries = ids.map((id) => `  ${JSON.stringify(id)}: ${entry},`).join('\n');
  return `export const mutationOwnerContract = {\n${entries}\n};\n`;
}


async function expectReject(operation, pattern) {
  let error = null;
  try {
    await operation();
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof Error, 'operation should reject');
  assert.match(error.message, pattern);
}


const fixtureRoot = await mkdtemp(path.join(os.tmpdir(), 'fbm-mutation-inventory-'));
try {
  const frontendRoot = path.join(fixtureRoot, 'frontend');
  const apiFile = path.join(frontendRoot, 'src/api/index.ts');
  const workflowRegistryFile = path.join(frontendRoot, 'src/workflow/productWorkflowActionRegistry.ts');
  const rootPage = path.join(frontendRoot, 'src/pages/Root.tsx');
  const otherPage = path.join(frontendRoot, 'src/pages/OtherPage.tsx');
  const secondary = path.join(frontendRoot, 'src/components/Secondary.tsx');
  const outputFile = path.join(frontendRoot, 'src/api/mutationInventory.generated.ts');
  const ownerContractFile = path.join(frontendRoot, 'src/api/mutationOwnerContract.ts');
  await mkdir(path.dirname(apiFile), { recursive: true });
  await mkdir(path.dirname(workflowRegistryFile), { recursive: true });
  await mkdir(path.dirname(rootPage), { recursive: true });
  await mkdir(path.dirname(secondary), { recursive: true });

  const apiSource = `
const api = {
  post: (...args: unknown[]) => args,
  patch: (...args: unknown[]) => args,
  delete: (...args: unknown[]) => args,
  get: (...args: unknown[]) => args,
};
export const saveProduct = () => api.post('/products');
export const removeProduct = () => api.delete('/products/1');
export function functionSave() { return api.post('/function-save'); }
export const workflowRetry = () => api.post('/workflow-retry');
export const workflowResume = () => api.post('/workflow-resume');
export const unusedInternal = () => api.patch('/internal');
export const readProduct = () => api.get('/products/1');
`;
  const workflowRegistrySource = `
import { workflowRetry as retryClient } from '../api';
export const PRODUCT_WORKFLOW_API_CLIENT_BINDINGS = {
  workflowRetry: { execute: retryClient },
};
export async function dispatchProductWorkflowAction(
  _action: string,
  context: { productId: number; mutationMetadata?: unknown; apiClientOverride?: (...args: unknown[]) => unknown },
) {
  const selectedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const selectedExecute = context.apiClientOverride || selectedBinding.execute;
  await selectedExecute(context.productId, context.mutationMetadata);
}
`;
  const rootSource = `
import { functionSave, saveProduct as save } from '../api';
import { Secondary } from '../components/Secondary';
import { dispatchProductWorkflowAction as dispatchWorkflow } from '../workflow/productWorkflowActionRegistry';
export function Root() {
  const handleSave = async () => {
    await save();
    await save();
    await functionSave();
  };
  const handleWorkflow = async () => {
    await dispatchWorkflow('retry', { productId: 1 });
  };
  return <><Secondary onSave={handleSave} /><button onClick={handleWorkflow}>workflow</button></>;
}
`;
  const secondarySource = `
import * as apiClients from '../api';
export function Secondary(_props: { onSave: () => void }) {
  const handleOtherOwner = async () => {
    await apiClients.saveProduct();
    await apiClients.removeProduct();
  };
  return <button onClick={handleOtherOwner}>save</button>;
}
`;
  const otherPageSource = `
import * as workflowRegistry from '../workflow/productWorkflowActionRegistry';
export function OtherPage() {
  const handleOtherWorkflow = async () => {
    await workflowRegistry.dispatchProductWorkflowAction('retry', { productId: 2 });
  };
  return <button onClick={handleOtherWorkflow}>workflow</button>;
}
`;
  await writeFile(apiFile, apiSource, 'utf8');
  await writeFile(workflowRegistryFile, workflowRegistrySource, 'utf8');
  await writeFile(rootPage, rootSource, 'utf8');
  await writeFile(otherPage, otherPageSource, 'utf8');
  await writeFile(secondary, secondarySource, 'utf8');

  const allowlist = {
    unusedInternal: {
      classification: 'unused',
      reason: 'Fixture-only unused export verifies explicit classification.',
    },
    workflowResume: {
      classification: 'unused',
      reason: 'Fixture-only unused workflow client verifies registry binding additions cannot bypass the allowlist.',
    },
  };
  const options = {
    repoRoot: fixtureRoot,
    frontendRoot,
    apiFile,
    workflowRegistryFile,
    outputFile,
    ownerContractFile,
    requiredRoots: [rootPage],
    allowlist,
    staticWrapperCoverage: false,
  };
  const first = await analyzeMutationInventory(options);
  assert.equal(first.mutatingExports.length, 6);
  assert.equal(first.callsites.length, 7);
  assert.deepEqual(
    first.callsites.filter((item) => item.client === 'saveProduct' && item.handler === 'handleSave').map((item) => item.id),
    [
      'saveProduct|frontend/src/pages/Root.tsx|handleSave|1',
      'saveProduct|frontend/src/pages/Root.tsx|handleSave|2',
    ],
  );
  assert.equal(first.callsites.filter((item) => item.client === 'saveProduct').length, 3);
  assert.deepEqual(
    first.callsites.filter((item) => item.client === 'workflowRetry').map((item) => item.id),
    [
      'workflowRetry|frontend/src/pages/OtherPage.tsx|handleOtherWorkflow',
      'workflowRetry|frontend/src/pages/Root.tsx|handleWorkflow',
    ],
  );
  assert(first.callsites.filter((item) => item.client === 'workflowRetry').every((item) => item.via === 'workflow_registry'));
  assert(first.callsites.some((item) => item.client === 'functionSave' && item.via === 'direct'));
  assert.equal(first.exceptions.length, 2);

  const idsBeforeLineMove = first.callsites.map((item) => item.id);
  await writeFile(rootPage, `\n// unrelated line movement\n${rootSource}`, 'utf8');
  const moved = await analyzeMutationInventory(options);
  assert.deepEqual(moved.callsites.map((item) => item.id), idsBeforeLineMove);

  await writeFile(outputFile, renderMutationInventory(first), 'utf8');
  await writeFile(ownerContractFile, renderOwnerContract(idsBeforeLineMove), 'utf8');
  await generateMutationInventory({ ...options, check: true });

  await writeFile(secondary, secondarySource.replace('    await apiClients.removeProduct();\n', ''), 'utf8');
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /stale|unclassified mutating exports.*removeProduct/i,
  );
  await writeFile(secondary, secondarySource, 'utf8');

  await writeFile(apiFile, apiSource.replace("export const removeProduct = () => api.delete('/products/1');\n", ''), 'utf8');
  await expectReject(() => generateMutationInventory({ ...options, check: true }), /stale|unknown imported API export|owner contract/i);
  await writeFile(apiFile, apiSource, 'utf8');

  await writeFile(
    workflowRegistryFile,
    workflowRegistrySource.replace('  workflowRetry: { execute: retryClient },\n', ''),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /unclassified mutating exports.*workflowRetry/i,
  );
  await writeFile(
    workflowRegistryFile,
    workflowRegistrySource.replace('workflowRetry: { execute: retryClient }', 'renamedWorkflowRetry: { execute: retryClient }'),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /key renamedWorkflowRetry must match execute API export workflowRetry/i,
  );
  await writeFile(
    workflowRegistryFile,
    workflowRegistrySource.replace(
      `  const selectedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const selectedExecute = context.apiClientOverride || selectedBinding.execute;
  await selectedExecute(context.productId, context.mutationMetadata);`,
      `  void PRODUCT_WORKFLOW_API_CLIENT_BINDINGS;
  return;`,
    ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /dispatchProductWorkflowAction must call an execute derived from a PRODUCT_WORKFLOW_API_CLIENT_BINDINGS binding lookup/i,
  );
  await writeFile(
    workflowRegistryFile,
    workflowRegistrySource.replace(
      `  const selectedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const selectedExecute = context.apiClientOverride || selectedBinding.execute;
  await selectedExecute(context.productId, context.mutationMetadata);`,
      `  const renamedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  void renamedBinding;`,
    ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /must call an execute derived from a .* binding lookup/i,
  );
  await writeFile(
    workflowRegistryFile,
    workflowRegistrySource.replace(
      `  const selectedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const selectedExecute = context.apiClientOverride || selectedBinding.execute;
  await selectedExecute(context.productId, context.mutationMetadata);`,
      `  const renamedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const renamedExecute = renamedBinding.execute;
  void renamedExecute;`,
    ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /must call an execute derived from a .* binding lookup/i,
  );
  await writeFile(
    workflowRegistryFile,
    workflowRegistrySource.replace(
      `  const selectedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const selectedExecute = context.apiClientOverride || selectedBinding.execute;
  await selectedExecute(context.productId, context.mutationMetadata);`,
      `  const renamedBinding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const renamedExecute = renamedBinding.execute;
  await unrelatedExecute();`,
    ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /must call an execute derived from a .* binding lookup/i,
  );
  await writeFile(
    workflowRegistryFile,
    workflowRegistrySource
      .replace(
        "import { workflowRetry as retryClient } from '../api';",
        "import { workflowResume, workflowRetry as retryClient } from '../api';",
      )
      .replace(
        '  workflowRetry: { execute: retryClient },',
        '  workflowRetry: { execute: retryClient },\n  workflowResume: { execute: workflowResume },',
      ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /allowlist exports now have owner callsites.*workflowResume/i,
  );
  await writeFile(workflowRegistryFile, workflowRegistrySource, 'utf8');

  const missingContractId = idsBeforeLineMove[0];
  await writeFile(
    ownerContractFile,
    renderOwnerContract(idsBeforeLineMove.filter((id) => id !== missingContractId)),
    'utf8',
  );
  await expectReject(() => generateMutationInventory({ ...options, check: true }), /owner contract/i);

  await writeFile(
    ownerContractFile,
    renderOwnerContract(idsBeforeLineMove, ownerEntry.replace("  catch_policy: 'D2b pending: preserve owner state and show apiErrorMessage',\n", '')),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /owner contract entry .* missing fields: catch_policy/i,
  );
  await writeFile(
    ownerContractFile,
    renderOwnerContract(idsBeforeLineMove, ownerEntry.replace("owner_state: 'fixture state'", "owner_state: '   '")),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /owner contract entry .*owner_state must be a non-empty static string/i,
  );
  await writeFile(
    ownerContractFile,
    renderOwnerContract(idsBeforeLineMove, ownerEntry.replace('\n}', "\n  extra_policy: 'not allowed',\n}")),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...options, check: true }),
    /owner contract entry .* has unknown field extra_policy/i,
  );
  await writeFile(ownerContractFile, renderOwnerContract(idsBeforeLineMove), 'utf8');

  await expectReject(
    () => analyzeMutationInventory({ ...options, allowlist: {} }),
    /unclassified mutating exports.*unusedInternal/i,
  );
  await expectReject(
    () => analyzeMutationInventory({
      ...options,
      allowlist: {
        ...allowlist,
        missingExport: { classification: 'unused', reason: 'Must fail unknown allowlist entries.' },
      },
    }),
    /unknown allowlist exports.*missingExport/i,
  );

  const d2bRoot = path.join(fixtureRoot, 'd2b');
  const d2bFrontendRoot = path.join(d2bRoot, 'frontend');
  const d2bApiFile = path.join(d2bFrontendRoot, 'src/api/index.ts');
  const d2bRunnerFile = path.join(d2bFrontendRoot, 'src/api/mutationRunner.ts');
  const d2bWorkflowFile = path.join(d2bFrontendRoot, 'src/workflow/productWorkflowActionRegistry.ts');
  const d2bPage = path.join(d2bFrontendRoot, 'src/pages/Root.tsx');
  const d2bOutput = path.join(d2bFrontendRoot, 'src/api/mutationInventory.generated.ts');
  const d2bOwnerContract = path.join(d2bFrontendRoot, 'src/api/mutationOwnerContract.ts');
  await mkdir(path.dirname(d2bApiFile), { recursive: true });
  await mkdir(path.dirname(d2bWorkflowFile), { recursive: true });
  await mkdir(path.dirname(d2bPage), { recursive: true });

  const d2bApiSource = `
export type MutationMetadataConfig = { fbmMutationCallsiteId?: string };
const mutationRequestConfig = (metadata?: MutationMetadataConfig) => ({ ...metadata });
const api = { post: (...args: unknown[]) => args };
export const saveProduct = (id: number, metadata?: MutationMetadataConfig) =>
  api.post('/products', { id }, mutationRequestConfig(metadata));
export const workflowRetry = (id: number, metadata?: MutationMetadataConfig) =>
  api.post('/products/retry', { id }, mutationRequestConfig(metadata));
`;
  const d2bRunnerSource = `
export async function runMutationWithUX(
  _id: string,
  operation: (metadata: { fbmMutationCallsiteId?: string }) => Promise<unknown>,
  owners: { errorFallback: string; onError: (message: string) => void; clearLoading: () => void },
) {
  try { return await operation({}); }
  catch (error) { owners.onError(owners.errorFallback); throw error; }
  finally { owners.clearLoading(); }
}
`;
  const d2bWorkflowSource = `
import { workflowRetry } from '../api';
export const PRODUCT_WORKFLOW_API_CLIENT_BINDINGS = {
  workflowRetry: { execute: workflowRetry },
};
export async function dispatchProductWorkflowAction(
  _action: string,
  context: { productId: number; mutationMetadata?: { fbmMutationCallsiteId?: string } },
) {
  const binding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS.workflowRetry;
  const execute = binding.execute;
  await execute(context.productId, context.mutationMetadata);
}
`;
  const directId = 'saveProduct|frontend/src/pages/Root.tsx|handleSave';
  const workflowId = 'workflowRetry|frontend/src/pages/Root.tsx|handleWorkflow';
  const d2bRootSource = `
import { useState } from 'react';
import { message } from 'antd';
import { saveProduct } from '../api';
import { runMutationWithUX } from '../api/mutationRunner';
import { dispatchProductWorkflowAction } from '../workflow/productWorkflowActionRegistry';
const FIXTURE_WORKFLOW_CALLSITE_IDS = {
  workflowRetry: ${JSON.stringify(workflowId)},
} as const;
export function Root() {
  const [draft] = useState('keep');
  const [fixtureLoading, setFixtureLoading] = useState(false);
  const handleSave = async () => {
    setFixtureLoading(true);
    await runMutationWithUX(
      ${JSON.stringify(directId)},
      async (metadata) => { await saveProduct(1, metadata); },
      {
        errorFallback: 'save failed',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setFixtureLoading(false),
      },
    ).catch(() => undefined);
  };
  const handleWorkflow = async () => {
    const definition = { client_export: 'workflowRetry' } as const;
    setFixtureLoading(true);
    await runMutationWithUX(
      FIXTURE_WORKFLOW_CALLSITE_IDS[definition.client_export],
      async (metadata) => {
        await dispatchProductWorkflowAction('retry', { productId: 1, mutationMetadata: metadata });
      },
      {
        errorFallback: 'workflow failed',
        onError: (errorMessage) => message.error(errorMessage),
        clearLoading: () => setFixtureLoading(false),
      },
    ).catch(() => undefined);
  };
  return <button data-draft={draft} onClick={handleSave} onDoubleClick={handleWorkflow}>save</button>;
}
`;
  const d2bOwnerSource = `export const mutationOwnerContract = {
  ${JSON.stringify(directId)}: {
    owner_component: 'Root',
    owner_state: 'draft',
    loading_state: 'fixtureLoading',
    catch_policy: 'runMutationWithUX apiErrorMessage -> message.error; preserve draft',
    finally_policy: 'runMutationWithUX clearLoading: fixtureLoading',
    playwright_case: 'runtime case: fixture direct',
  },
  ${JSON.stringify(workflowId)}: {
    owner_component: 'Root',
    owner_state: 'draft',
    loading_state: 'fixtureLoading',
    catch_policy: 'runMutationWithUX apiErrorMessage -> message.error; preserve draft',
    finally_policy: 'runMutationWithUX clearLoading: fixtureLoading',
    playwright_case: 'runtime case: fixture workflow',
  },
};
`;
  await writeFile(d2bApiFile, d2bApiSource, 'utf8');
  await writeFile(d2bRunnerFile, d2bRunnerSource, 'utf8');
  await writeFile(d2bWorkflowFile, d2bWorkflowSource, 'utf8');
  await writeFile(d2bPage, d2bRootSource, 'utf8');
  await writeFile(d2bOwnerContract, d2bOwnerSource, 'utf8');
  const d2bOptions = {
    repoRoot: d2bRoot,
    frontendRoot: d2bFrontendRoot,
    apiFile: d2bApiFile,
    mutationRunnerFile: d2bRunnerFile,
    workflowRegistryFile: d2bWorkflowFile,
    outputFile: d2bOutput,
    ownerContractFile: d2bOwnerContract,
    requiredRoots: [d2bPage],
    allowlist: {},
  };
  const d2bAnalysis = await analyzeMutationInventory(d2bOptions);
  assert.deepEqual(d2bAnalysis.callsites.map((item) => item.id), [directId, workflowId]);
  await writeFile(
    d2bOutput,
    renderMutationInventory(d2bAnalysis, { staticWrapperCoverageEnabled: true }),
    'utf8',
  );
  await generateMutationInventory({ ...d2bOptions, check: true });

  await writeFile(d2bPage, d2bRootSource.replace(directId, `${directId}-wrong`), 'utf8');
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /unknown or non-direct callsite id|static coverage mismatch/i,
  );
  await writeFile(d2bPage, d2bRootSource.replace('message.error(errorMessage)', 'message.info(errorMessage)'), 'utf8');
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /onError must call message\.error\(messageParam\) once/i,
  );
  await writeFile(
    d2bPage,
    d2bRootSource.replace(
      'onError: (errorMessage) => message.error(errorMessage)',
      'onError: (errorMessage) => { const deadToast = () => message.error(errorMessage); void deadToast; }',
    ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /onError must call message\.error\(messageParam\) once/i,
  );
  await writeFile(
    d2bPage,
    d2bRootSource.replace(
      'onError: (errorMessage) => message.error(errorMessage)',
      "onError: (errorMessage) => { message.error(errorMessage); message.error('extra'); }",
    ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /onError must call message\.error\(messageParam\) once/i,
  );
  await writeFile(d2bPage, d2bRootSource.replace('clearLoading: () => setFixtureLoading(false)', 'clearLoading: () => undefined'), 'utf8');
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /clearLoading must call setFixtureLoading\(false\) once/i,
  );
  await writeFile(
    d2bPage,
    d2bRootSource.replace('setFixtureLoading(false)', 'setFixtureLoading(true)'),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /clearLoading must call setFixtureLoading\(false\) once/i,
  );
  await writeFile(
    d2bPage,
    d2bRootSource.replace(
      'clearLoading: () => setFixtureLoading(false)',
      'clearLoading: () => { const deadClear = () => setFixtureLoading(false); void deadClear; }',
    ),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /clearLoading must call setFixtureLoading\(false\) once/i,
  );
  await writeFile(
    d2bPage,
    d2bRootSource.replace('.catch(() => undefined)', '.catch((error) => { throw error; })'),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /must swallow the runner rethrow with \.catch\(\(\) => undefined\)/i,
  );
  await writeFile(d2bPage, d2bRootSource.replace('saveProduct(1, metadata)', 'saveProduct(1)'), 'utf8');
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /must call saveProduct once with operation metadata/i,
  );
  await writeFile(
    d2bPage,
    d2bRootSource.replace(', mutationMetadata: metadata', ''),
    'utf8',
  );
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /must dispatch once with mutationMetadata/i,
  );
  await writeFile(
    d2bApiFile,
    d2bApiSource.replace('mutationRequestConfig(metadata));', '{});'),
    'utf8',
  );
  await writeFile(d2bPage, d2bRootSource, 'utf8');
  await expectReject(
    () => generateMutationInventory({ ...d2bOptions, check: true }),
    /must pass metadata through mutationRequestConfig/i,
  );
  await writeFile(d2bApiFile, d2bApiSource, 'utf8');

  const generatedText = await readFile(outputFile, 'utf8');
  assert.match(generatedText, /D2b static wrapper coverage: not-enabled/);
  assert.match(generatedText, /"via": "workflow_registry"/);
  console.log('Mutation inventory AST fixture checks passed');
} finally {
  await rm(fixtureRoot, { recursive: true, force: true });
}
