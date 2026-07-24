import {
  resumePipeline,
  retryProductAutoImageSelection,
  retryProductCompetitorSearch,
  retryProductCompetitorVisualMatch,
  retryStep,
} from '../api/index.ts';
import type { MutationMetadataConfig } from '../api/index.ts';
import {
  PRODUCT_WORKFLOW_ACTIONS,
  type GeneratedProductWorkflowAction,
} from './productWorkflowActions.generated.ts';

export type ProductWorkflowAction = GeneratedProductWorkflowAction;
export type ProductWorkflowActionDefinition = (typeof PRODUCT_WORKFLOW_ACTIONS)[number];
export type ProductWorkflowApiActionDefinition = Extract<ProductWorkflowActionDefinition, { kind: 'api' }>;
export type ProductWorkflowNavigateActionDefinition = Extract<ProductWorkflowActionDefinition, { kind: 'navigate' }>;
export type ProductWorkflowApiAction = ProductWorkflowApiActionDefinition['action'];
export type ProductWorkflowApiClientExport = ProductWorkflowApiActionDefinition['client_export'];
export type ProductWorkflowApiClient = (
  productId: number,
  metadata?: MutationMetadataConfig,
) => unknown | Promise<unknown>;
export type ProductWorkflowApiClientBinding = {
  execute: ProductWorkflowApiClient;
  method: ProductWorkflowApiActionDefinition['method'];
  route: ProductWorkflowApiActionDefinition['route'];
};
export type ProductWorkflowDispatchContext = {
  productId?: number | null;
  relatedCorrelationKey?: string | null;
  mutationMetadata?: MutationMetadataConfig;
  navigate?: (target: string) => void | Promise<void>;
  apiClientOverrides?: Partial<Record<ProductWorkflowApiClientExport, ProductWorkflowApiClient>>;
};
export type ProductWorkflowDispatchResult = {
  status: 'handled' | 'missing' | 'unknown' | 'unavailable';
  action: string | null;
};

export const PRODUCT_WORKFLOW_API_CLIENT_BINDINGS = {
  retryProductAutoImageSelection: {
    execute: retryProductAutoImageSelection,
    method: 'POST',
    route: '/api/products/{product_id}/auto-image-selection/retry',
  },
  retryProductCompetitorSearch: {
    execute: retryProductCompetitorSearch,
    method: 'POST',
    route: '/api/products/{product_id}/competitor-search/retry',
  },
  retryProductCompetitorVisualMatch: {
    execute: retryProductCompetitorVisualMatch,
    method: 'POST',
    route: '/api/products/{product_id}/competitor-visual-match/retry',
  },
  retryStep: {
    execute: retryStep,
    method: 'POST',
    route: '/api/products/{product_id}/retry',
  },
  resumePipeline: {
    execute: resumePipeline,
    method: 'POST',
    route: '/api/products/{product_id}/resume',
  },
} satisfies Record<ProductWorkflowApiClientExport, ProductWorkflowApiClientBinding>;

export const EXPECTED_PRODUCT_WORKFLOW_API_CLIENTS = {
  restart_competitor_search: 'retryProductCompetitorSearch',
  resume: 'resumePipeline',
  retry: 'retryStep',
  retry_auto_image_selection: 'retryProductAutoImageSelection',
  retry_competitor_search: 'retryProductCompetitorSearch',
  retry_competitor_visual_match: 'retryProductCompetitorVisualMatch',
  retry_image_analysis: 'retryStep',
  retry_listing_generation: 'retryStep',
  start_competitor_search: 'retryProductCompetitorSearch',
} satisfies Record<ProductWorkflowApiAction, ProductWorkflowApiClientExport>;

const ACTIONS_BY_NAME = new Map<string, ProductWorkflowActionDefinition>(
  PRODUCT_WORKFLOW_ACTIONS.map((definition) => [definition.action, definition]),
);

export const getProductWorkflowAction = (action?: string | null): ProductWorkflowActionDefinition | null => (
  action ? ACTIONS_BY_NAME.get(action) || null : null
);

export const isKnownProductWorkflowAction = (action?: string | null): action is ProductWorkflowAction => (
  Boolean(getProductWorkflowAction(action))
);

export const productWorkflowActionDiagnostic = (action?: string | null) => (
  `未知工作流动作：${action || '(empty)'}`
);

export const reportUnknownProductWorkflowAction = (action?: string | null) => {
  const env = (import.meta as ImportMeta & { env?: { DEV?: boolean; MODE?: string } }).env;
  if (!env || env.DEV || env.MODE === 'test') {
    console.error(productWorkflowActionDiagnostic(action));
  }
};

const navigationTarget = (
  definition: ProductWorkflowNavigateActionDefinition,
  context: ProductWorkflowDispatchContext,
): string | null => {
  if (definition.target.includes('{product_id}') && !context.productId) return null;
  if (definition.target.includes('{related_correlation_key}') && !context.relatedCorrelationKey) {
    return definition.target.split('?', 1)[0];
  }
  return definition.target
    .replace('{product_id}', encodeURIComponent(String(context.productId)))
    .replace('{related_correlation_key}', encodeURIComponent(String(context.relatedCorrelationKey)));
};

export async function dispatchProductWorkflowAction(
  action: string | null | undefined,
  context: ProductWorkflowDispatchContext,
): Promise<ProductWorkflowDispatchResult> {
  if (!action) return { status: 'missing', action: null };
  const definition = getProductWorkflowAction(action);
  if (!definition) {
    reportUnknownProductWorkflowAction(action);
    return { status: 'unknown', action };
  }
  if (definition.kind === 'navigate') {
    const target = navigationTarget(definition, context);
    if (!target || !context.navigate) return { status: 'unavailable', action };
    await context.navigate(target);
    return { status: 'handled', action };
  }
  if (!context.productId) return { status: 'unavailable', action };
  const binding = PRODUCT_WORKFLOW_API_CLIENT_BINDINGS[definition.client_export];
  const execute = context.apiClientOverrides?.[definition.client_export] || binding.execute;
  await execute(context.productId, context.mutationMetadata);
  return { status: 'handled', action };
}
