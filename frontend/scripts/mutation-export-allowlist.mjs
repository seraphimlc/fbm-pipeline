export const mutationExportAllowlist = {
  importProducts: {
    classification: 'unused',
    reason: 'The upload client remains available for compatibility, but no current pages/components/hooks owner invokes it.',
  },
  bulkStartPipelines: {
    classification: 'unused',
    reason: 'The legacy direct bulk-start client has no current pages/components/hooks owner; task-based advance is used instead.',
  },
  autoStartReadyGeneration: {
    classification: 'unused',
    reason: 'The automatic ready-generation client is not currently exposed by a pages/components/hooks owner.',
  },
  createProductBulkAdvanceTask: {
    classification: 'unused',
    reason: 'The explicit-id bulk advance client has no current pages/components/hooks owner; the filter-based owner is active.',
  },
  exportCatalogProducts: {
    classification: 'unused',
    reason: 'The legacy direct catalog blob export is retained, while the current CatalogList owner creates task runs.',
  },
  exportCatalogProductsByCategory: {
    classification: 'unused',
    reason: 'The legacy category blob export is retained, while the current CatalogList owner creates task runs.',
  },
  exportInventoryUpdateTemplate: {
    classification: 'unused',
    reason: 'The inventory-template export client currently has no pages/components/hooks owner.',
  },
  updateCatalogAsin: {
    classification: 'unused',
    reason: 'Catalog ASIN mutation is not currently exposed by a pages/components/hooks owner.',
  },
  clearCatalogAsin: {
    classification: 'unused',
    reason: 'Catalog ASIN deletion is not currently exposed by a pages/components/hooks owner.',
  },
  createInventorySyncBatch: {
    classification: 'unused',
    reason: 'The legacy inventory sync batch client has no current owner; task-run based GIGA inventory sync is active.',
  },
  syncMissingGigaProducts: {
    classification: 'unused',
    reason: 'The synchronous missing-product client has no current owner; the task-run pull client is active.',
  },
  syncMissingGigaProductsBackground: {
    classification: 'unused',
    reason: 'The legacy background missing-product client has no current pages/components/hooks owner.',
  },
  syncGigaInventory: {
    classification: 'unused',
    reason: 'The direct GIGA inventory sync client has no current owner; task-run based sync is active.',
  },
  syncGigaPrice: {
    classification: 'unused',
    reason: 'The direct GIGA price sync client has no current owner; task-run based sync is active.',
  },
  createAsinSyncBatch: {
    classification: 'unused',
    reason: 'ASIN sync creation is not currently exposed by a pages/components/hooks owner.',
  },
  createAplusUploadBatch: {
    classification: 'unused',
    reason: 'A+ upload batch creation is not currently exposed by a pages/components/hooks owner.',
  },
  confirmProduct: {
    classification: 'unused',
    reason: 'The legacy product confirmation client has no current pages/components/hooks owner.',
  },
  refreshProductFromGiga: {
    classification: 'unused',
    reason: 'The direct product refresh client has no current pages/components/hooks owner.',
  },
  runPipelineStep: {
    classification: 'unused',
    reason: 'The direct single-step pipeline client has no current pages/components/hooks owner.',
  },
};
