/**
 * Type declarations for openclaw/plugin-sdk modules.
 * These are provided by the OpenClaw runtime at load time.
 */

declare module "openclaw/plugin-sdk/plugin-entry" {
  interface PluginEntry {
    id: string;
    name: string;
    description: string;
    kind?: string;
    configSchema?: Record<string, unknown>;
    register(api: OpenClawPluginApi): void;
  }

  interface OpenClawPluginApi {
    id: string;
    name: string;
    version?: string;
    description?: string;
    source: string;
    rootDir?: string;
    config: Record<string, unknown>;
    pluginConfig: Record<string, unknown>;
    logger: {
      debug(msg: string, ...args: unknown[]): void;
      info(msg: string, ...args: unknown[]): void;
      warn(msg: string, ...args: unknown[]): void;
      error(msg: string, ...args: unknown[]): void;
    };

    registerContextEngine(
      id: string,
      factory: () => ContextEngine,
    ): void;
    registerProvider(...args: unknown[]): void;
    registerTool(...args: unknown[]): void;
    registerHook(...args: unknown[]): void;
    registerHttpRoute(...args: unknown[]): void;
    registerCommand(...args: unknown[]): void;
    registerService(...args: unknown[]): void;
    on(event: string, handler: (...args: unknown[]) => void, opts?: unknown): void;
  }

  interface ContextEngineInfo {
    id: string;
    name: string;
    ownsCompaction: boolean;
  }

  interface IngestParams {
    sessionId: string;
    message: Record<string, unknown>;
    isHeartbeat?: boolean;
  }

  interface AssembleParams {
    sessionId: string;
    messages: Array<Record<string, unknown>>;
    tokenBudget: number;
    availableTools?: Set<string>;
    citationsMode?: string;
  }

  interface AssembleResult {
    messages: Array<Record<string, unknown>>;
    estimatedTokens: number;
    systemPromptAddition?: string;
  }

  interface CompactParams {
    sessionId: string;
    force?: boolean;
    runtimeContext?: Record<string, unknown>;
    sessionFile?: string;
    tokenBudget?: number;
    currentTokenCount?: number;
    customInstructions?: string;
    compactionTarget?: string;
  }

  interface CompactResult {
    ok: boolean;
    compacted?: boolean;
    reason?: string;
    result?: {
      summary?: string;
      firstKeptEntryId?: string;
      tokensBefore?: number;
      tokensAfter?: number;
      details?: string;
    };
  }

  interface AfterTurnParams {
    sessionId: string;
    messages: Array<Record<string, unknown>>;
  }

  interface ContextEngine {
    info: ContextEngineInfo;
    ingest(params: IngestParams): Promise<{ ingested?: boolean }>;
    assemble(params: AssembleParams): Promise<AssembleResult>;
    compact(params: CompactParams): Promise<CompactResult>;
    afterTurn?(params: AfterTurnParams): Promise<void>;
    bootstrap?(params: { sessionId: string }): Promise<void>;
    ingestBatch?(params: { sessionId: string; messages: Array<Record<string, unknown>> }): Promise<void>;
    prepareSubagentSpawn?(params: Record<string, unknown>): Promise<void>;
    onSubagentEnded?(params: Record<string, unknown>): Promise<void>;
    dispose?(): void;
  }

  export function definePluginEntry(entry: PluginEntry): PluginEntry;
}

declare module "openclaw/plugin-sdk/core" {
  import type { CompactParams, CompactResult } from "openclaw/plugin-sdk/plugin-entry";

  export function registerContextEngine(
    id: string,
    factory: () => unknown,
  ): void;

  export function delegateCompactionToRuntime(
    params: CompactParams,
  ): Promise<CompactResult>;

  export function buildMemorySystemPromptAddition(params: {
    availableTools: Set<string>;
    citationsMode?: string;
  }): string | undefined;

  export function emptyPluginConfigSchema(): Record<string, unknown>;
}
