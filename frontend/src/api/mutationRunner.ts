import { apiErrorMessage, type MutationMetadataConfig } from './index.ts';
import type { MutationCallsiteId } from './mutationInventory.generated.ts';


export interface MutationUXOwners {
  clearLoading: () => void;
  errorFallback: string;
  onError: (message: string, error: unknown) => void;
}

export async function runMutationWithUX<T>(
  callsiteId: MutationCallsiteId,
  operation: (metadataConfig: MutationMetadataConfig) => Promise<T> | T,
  owners: MutationUXOwners,
): Promise<T> {
  try {
    return await operation({ fbmMutationCallsiteId: callsiteId });
  } catch (error) {
    owners.onError(apiErrorMessage(error, owners.errorFallback), error);
    throw error;
  } finally {
    owners.clearLoading();
  }
}
