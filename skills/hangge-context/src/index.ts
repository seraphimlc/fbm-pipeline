/**
 * Hangge Context Engine Plugin v4
 *
 * Native OpenClaw Context Engine plugin (TypeScript).
 * Integrates Hangge Assistant memory system + skill auto-generation + task tracking.
 *
 * Lifecycle:
 *   ingest()     → index messages for pattern detection
 *   assemble()   → query memories + inject active tasks into systemPromptAddition
 *   compact()    → delegate to OpenClaw built-in compaction
 *   afterTurn()  → tool call monitoring, error recovery, task step detection, auto-extract
 */

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import {
  registerContextEngine,
  delegateCompactionToRuntime,
  buildMemorySystemPromptAddition,
} from "openclaw/plugin-sdk/core";

// ─── Types ───────────────────────────────────────────────────────────────────

interface PluginConfig {
  apiUrl: string;
  maxMemories: number;
  minRelevance: number;
  skillMonitorEnabled: boolean;
}

interface MemoryItem {
  id: string;
  content: string;
  category: string;
  relevance_score?: number;
}

interface ContextFragment {
  id: string;
  content: string;
  source: string;
  relevance_score?: number;
}

interface ToolCall {
  tool: string;
  params: string;
}

interface ErrorDetection {
  error_type: string;
  error_message: string;
}

interface CorrectionDetection {
  original_action: string;
  corrected_action: string;
  context: string;
}

interface ActiveTask {
  id: string;
  title: string;
  status: string;
  progress: number;
  priority: string;
  parent_task_id: string | null;
}

interface ChatMessage {
  role: string;
  content?: string;
  tool_calls?: Array<{
    name?: string;
    function?: { name?: string; arguments?: string | Record<string, unknown> };
    id?: string;
    type?: string;
  }>;
}

// ─── Session State ───────────────────────────────────────────────────────────

const sessionOperations = new Map<string, ToolCall[]>();
const lastAssistantAction = new Map<string, string>();
const currentTaskId = new Map<string, string>();

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getConfig(pluginConfig: Record<string, unknown>): PluginConfig {
  return {
    apiUrl: (pluginConfig.apiUrl as string) || "http://localhost:8000",
    maxMemories: (pluginConfig.maxMemories as number) ?? 5,
    minRelevance: (pluginConfig.minRelevance as number) ?? 0.3,
    skillMonitorEnabled: (pluginConfig.skillMonitorEnabled as boolean) ?? true,
  };
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T | null> {
  try {
    const resp = await fetch(url, {
      signal: AbortSignal.timeout(8000),
      ...init,
    });
    if (!resp.ok) return null;
    return (await resp.json()) as T;
  } catch {
    return null;
  }
}

// ─── Memory Query ────────────────────────────────────────────────────────────

async function queryMemories(
  apiUrl: string,
  query: string,
  limit: number,
): Promise<MemoryItem[]> {
  const url = `${apiUrl}/api/v1/memories/search?q=${encodeURIComponent(query)}&limit=${limit}`;
  const data = await fetchJSON<{ items: MemoryItem[] }>(url);
  return data?.items ?? [];
}

async function queryContext(
  apiUrl: string,
  query: string,
  limit: number,
): Promise<ContextFragment[]> {
  const url = `${apiUrl}/api/v1/context/query`;
  const data = await fetchJSON<{ fragments: ContextFragment[] }>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit }),
  });
  return data?.fragments ?? [];
}

function buildMemoryPromptAddition(
  memories: MemoryItem[],
  fragments: ContextFragment[],
): string | undefined {
  const lines: string[] = [];
  if (memories.length > 0) {
    lines.push("## 相关记忆");
    for (const mem of memories) {
      lines.push(`- [${mem.category}] ${mem.content}`);
    }
  }
  if (fragments.length > 0) {
    lines.push("## 相关上下文");
    for (const frag of fragments) {
      lines.push(`- [${frag.source}] ${frag.content}`);
    }
  }
  return lines.length > 0 ? lines.join("\n") : undefined;
}

// ─── Task Integration ────────────────────────────────────────────────────────

async function getActiveTasks(apiUrl: string): Promise<ActiveTask[]> {
  const data = await fetchJSON<ActiveTask[]>(`${apiUrl}/api/v1/tasks/active-summary`);
  return data ?? [];
}

async function autoExtractTask(
  apiUrl: string,
  content: string,
  sessionId: string,
  overrideTitle?: string,
): Promise<{ task_id: string } | null> {
  const body: Record<string, string> = { content, session_id: sessionId };
  if (overrideTitle) body.title = overrideTitle;
  const data = await fetchJSON<{ extracted: boolean; task_id?: string }>(
    `${apiUrl}/api/v1/tasks/auto-extract`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (data?.extracted && data.task_id) {
    return { task_id: data.task_id };
  }
  return null;
}

async function updateTaskProgress(
  apiUrl: string,
  taskId: string,
  completedSteps: number,
  message: string,
): Promise<void> {
  await fetchJSON(`${apiUrl}/api/v1/tasks/${taskId}/progress`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ completed_steps: completedSteps, message }),
  });
}

// Detect multi-step plans
const STEP_PATTERNS: RegExp[] = [
  /迭代\s*\d+\s*[到至]\s*\d+/,
  /分\s*\d+\s*步/,
  /\d+\s*个步骤/,
  /^\s*\d+[.、)]\s*.+/m,
];

function detectMultiStepPlan(content: string): boolean {
  return STEP_PATTERNS.some((p) => p.test(content));
}

// Detect step completion
const STEP_COMPLETE_PATTERNS: RegExp[] = [
  /迭代\d+完成/,
  /步骤\d+完成/,
  /✅\s*.+/,
  /完成[了]?[：:]\s*.+/,
];

function detectStepCompletion(content: string): string | null {
  for (const p of STEP_COMPLETE_PATTERNS) {
    const match = p.exec(content);
    if (match) return match[0].slice(0, 100);
  }
  return null;
}

// ─── Tool Call Extraction ────────────────────────────────────────────────────

function extractToolCalls(message: ChatMessage): ToolCall[] {
  const results: ToolCall[] = [];
  const toolCalls = message.tool_calls ?? [];
  for (const tc of toolCalls) {
    const name = tc.name ?? tc.function?.name ?? "";
    let args = tc.function?.arguments ?? {};
    if (typeof args === "string") {
      try { args = JSON.parse(args); } catch { args = { raw: args }; }
    }
    if (name) {
      results.push({ tool: name, params: JSON.stringify(args) });
    }
  }
  return results;
}

// ─── Error Detection ─────────────────────────────────────────────────────────

const ERROR_PATTERNS: Array<[RegExp, string]> = [
  [/Error:\s*(.+?)(?:\n|$)/, "RuntimeError"],
  [/ModuleNotFoundError:\s*No module named ['"](.+?)['"]/, "ModuleNotFoundError"],
  [/FileNotFoundError:\s*(.+?)(?:\n|$)/, "FileNotFoundError"],
  [/Permission denied:\s*(.+?)(?:\n|$)/, "PermissionError"],
  [/Command failed:\s*(.+?)(?:\n|$)/, "CommandFailed"],
  [/error TS\d+:\s*(.+?)(?:\n|$)/, "TypeError"],
];

function detectError(content: string): ErrorDetection | null {
  for (const [pattern, errorType] of ERROR_PATTERNS) {
    const match = pattern.exec(content);
    if (match) {
      return { error_type: errorType, error_message: match[0].slice(0, 200) };
    }
  }
  return null;
}

// ─── User Correction Detection ───────────────────────────────────────────────

const CORRECTION_PATTERNS: Array<[RegExp, string]> = [
  [/不对[，,]?(.+?)(?:[。.]|$)/, "zh"],
  [/不是[，,]?(.+?)(?:[。.]|$)/, "zh"],
  [/应该是(.+?)(?:[。.]|$)/, "zh"],
  [/错了[，,]?(.+?)(?:[。.]|$)/, "zh"],
  [/不要(.+?)(?:[，,.]|$)/, "zh"],
  [/No[,!]\s*(.+?)(?:$|\n)/, "en"],
  [/Wrong[,!]\s*(.+?)(?:$|\n)/, "en"],
  [/Actually[,\s]+(.+?)(?:$|\n)/, "en"],
];

function detectCorrection(content: string, sessionId: string): CorrectionDetection | null {
  for (const [pattern] of CORRECTION_PATTERNS) {
    const match = pattern.exec(content);
    if (match) {
      return {
        original_action: lastAssistantAction.get(sessionId) ?? "unknown",
        corrected_action: match[1]?.slice(0, 200) ?? "",
        context: content.slice(0, 300),
      };
    }
  }
  return null;
}

// ─── Skill Trigger Reporting ─────────────────────────────────────────────────

async function reportOperations(
  apiUrl: string, sessionId: string, operations: ToolCall[], patternType: string,
): Promise<void> {
  const url = `${apiUrl}/api/v1/skills/trigger/operations?session_id=${encodeURIComponent(sessionId)}&pattern_type=${encodeURIComponent(patternType)}`;
  const data = await fetchJSON<{ triggered?: boolean; template_id?: string }>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(operations),
  });
  if (data?.triggered) console.log(`[hangge-context] 🎉 技能自动生成: ${data.template_id ?? ""}`);
}

async function reportErrorRecovery(
  apiUrl: string, sessionId: string, errorType: string, errorMessage: string, recoverySteps: ToolCall[],
): Promise<void> {
  const url = `${apiUrl}/api/v1/skills/trigger/error-recovery?session_id=${encodeURIComponent(sessionId)}&error_type=${encodeURIComponent(errorType)}&error_message=${encodeURIComponent(errorMessage)}`;
  const data = await fetchJSON<{ triggered?: boolean; template_id?: string }>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(recoverySteps),
  });
  if (data?.triggered) console.log(`[hangge-context] 🎉 错误恢复技能生成: ${data.template_id ?? ""}`);
}

async function reportUserCorrection(
  apiUrl: string, sessionId: string, original: string, corrected: string, context: string,
): Promise<void> {
  const url = `${apiUrl}/api/v1/skills/trigger/user-correction?session_id=${encodeURIComponent(sessionId)}&original_action=${encodeURIComponent(original)}&corrected_action=${encodeURIComponent(corrected)}&context=${encodeURIComponent(context)}`;
  const data = await fetchJSON<{ triggered?: boolean; template_id?: string }>(url, { method: "POST" });
  if (data?.triggered) console.log(`[hangge-context] 🎉 纠正技能生成: ${data.template_id ?? ""}`);
}

// ─── Assistant Plan Detection ────────────────────────────────────────────────

interface AssistantPlan {
  title: string;
  content: string;
  steps: string[];
}

// 助手消息中的多步骤/耗时计划模式
const ASSISTANT_PLAN_PATTERNS: Array<[RegExp, (m: RegExpMatchArray) => AssistantPlan]> = [
  // "改动1...改动2...改动3..." / "步骤1...步骤2..."
  [
    /(?:改动|步骤|阶段|部分|模块|任务)\s*\d/g,
    (m) => {
      const full = m.input!;
      const stepMatches = [...full.matchAll(/(?:改动|步骤|阶段|部分|模块|任务)\s*(\d+)[.、:：）)]?\s*([^\n]+)/g)];
      const steps = stepMatches.map(s => s[2]?.trim()).filter(Boolean);
      return {
        title: steps[0] ? steps[0].slice(0, 60) : "多步骤任务",
        content: full.slice(0, 500),
        steps,
      };
    },
  ],
  // "3个改动" / "分两步" / "需要4步"
  [
    /(?:需要|分|有|共)\s*(\d+)\s*(?:个|步|部分|阶段|改动|模块)/,
    (m) => ({
      title: `多步骤任务 (${m[1]}步)`,
      content: m.input!.slice(0, 500),
      steps: Array.from({ length: parseInt(m[1]) }, (_, i) => `步骤${i + 1}`),
    }),
  ],
  // 耗时估计 "需要5分钟" / "大约10分钟" / "耗时超过5分钟"
  [
    /(?:需要|大约|大概|预计|估计|耗时)\s*(\d+)\s*(?:分钟|min)/,
    (m) => {
      const minutes = parseInt(m[1]);
      if (minutes < 5) return null!;  // 不到5分钟不创建
      return {
        title: `耗时任务 (~${minutes}分钟)`,
        content: m.input!.slice(0, 500),
        steps: [],
      };
    },
  ],
  // "先...然后...最后..." / "第一步...第二步..."
  [
    /(?:先|首先|第一步)[\s\S]*?(?:然后|接着|第二步)[\s\S]*?(?:最后|最终|第三步)/,
    (m) => ({
      title: "多步骤任务",
      content: m.input!.slice(0, 500),
      steps: ["第一步", "第二步", "第三步"],
    }),
  ],
];

function detectAssistantPlan(content: string): AssistantPlan | null {
  for (const [pattern, extractor] of ASSISTANT_PLAN_PATTERNS) {
    const match = pattern.exec(content);
    if (match) {
      try {
        const plan = extractor(match);
        if (plan && (plan.steps.length >= 2 || plan.title.includes("耗时"))) {
          return plan;
        }
      } catch {
        // ignore extraction errors
      }
    }
  }
  return null;
}

// ─── Implicit Time Estimation ───────────────────────────────────────────────
// 检测工具调用参数中的耗时操作关键词，自动估算执行时间

const LONG_RUNNING_COMMANDS: Array<[RegExp, number]> = [
  // 编译/构建（通常3-15分钟）
  [/\b(?:npm|yarn|pnpm)\s+(?:install|ci|build|run\s+build)\b/, 8],
  [/\b(?:cargo|rustc)\s+(?:build|install|test)\b/, 10],
  [/\b(?:make|cmake|ninja)\b/, 5],
  [/\b(?:pip|uv)\s+(?:install|pip-install)\b/, 5],
  [/\bbundle\s+install\b/, 5],
  [/\bgo\s+(?:build|install|test|mod)\b/, 5],
  // 测试套件（通常2-10分钟）
  [/\b(?:pytest|jest|mocha|vitest|karma|ctest)\b/, 5],
  [/\b(?:npm|yarn|pnpm)\s+test\b/, 5],
  [/\bcargo\s+test\b/, 8],
  // 部署/发布（通常3-10分钟）
  [/\b(?:deploy|publish|release|docker\s+(?:build|push|compose))\b/, 8],
  [/\bkubectl\s+(?:apply|rollout|deploy)\b/, 5],
  [/\bterraform\s+(?:apply|plan)\b/, 10],
  // 数据处理（通常5-30分钟）
  [/\b(?:migrate|migration|seed|etl|import|export)\b/i, 8],
  [/\b(?:train|fine-?tun|embedding|index)\b/i, 15],
  // 下载/同步大文件
  [/\b(?:git\s+clone|rsync|wget|curl).{0,50}(?:--|\s)(?:repo|large|model|dataset)\b/i, 10],
  [/\bollama\s+pull\b/, 8],
  // AI/ML 相关
  [/\b(?:inference|generate|transcri|ocr|speech)\b/i, 5],
];

function estimateOperationTime(ops: ToolCall[]): number {
  let totalMinutes = 0;
  for (const op of ops) {
    const cmd = op.params ?? "";
    for (const [pattern, minutes] of LONG_RUNNING_COMMANDS) {
      if (pattern.test(cmd)) {
        totalMinutes += minutes;
        break;  // 每个操作只匹配一次
      }
    }
  }
  return totalMinutes;
}

// ─── Manual Skill Generation Trigger ─────────────────────────────────────────

const SKILL_SAVE_PATTERNS: RegExp[] = [
  /记住这个流程/, /保存这个操作/, /把这个变成技能/, /生成技能/,
  /记住这个/, /保存流程/, /固化这个/,
  /save this (?:flow|pattern|workflow)/i,
  /make (?:this|it) a skill/i,
  /remember this (?:flow|pattern)/i,
];

function detectSkillSaveIntent(content: string): boolean {
  return SKILL_SAVE_PATTERNS.some(p => p.test(content));
}

async function triggerManualSkillGeneration(
  apiUrl: string, sessionId: string, operations: ToolCall[],
): Promise<void> {
  if (operations.length < 1) {
    console.log(`[hangge-context] ⚠️ 无操作可生成技能`);
    return;
  }
  const url = `${apiUrl}/api/v1/skills/generate-from-operations?session_id=${encodeURIComponent(sessionId)}`;
  const data = await fetchJSON<{ success?: boolean; task_id?: string }>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(operations),
  });
  if (data?.success) console.log(`[hangge-context] ✅ 手动技能生成已提交: ${data.task_id ?? ""}`);
}

// ─── Plugin Entry ────────────────────────────────────────────────────────────

export default definePluginEntry({
  id: "hangge-context",
  name: "Hangge Context Engine",
  description: "Context engine plugin integrating Hangge Assistant memory + skill auto-gen + task tracking",
  kind: "context-engine",

  register(api) {
    const config = getConfig(api.pluginConfig ?? {});

    api.registerContextEngine("hangge-context", () => ({
      info: {
        id: "hangge-context",
        name: "Hangge Context Engine",
        ownsCompaction: false,
      },

      // ── ingest ────────────────────────────────────────────────────────
      async ingest({ sessionId, message }) {
        return { ingested: true };
      },

      // ── assemble ──────────────────────────────────────────────────────
      async assemble({ sessionId, messages, tokenBudget, availableTools, citationsMode }) {
        // 1. Build memory prompt addition
        const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
        const query = typeof lastUserMsg?.content === "string" ? lastUserMsg.content.slice(0, 100) : "";

        let hanggeAddition: string | undefined;
        if (query) {
          const [memories, fragments] = await Promise.all([
            queryMemories(config.apiUrl, query, config.maxMemories),
            queryContext(config.apiUrl, query, config.maxMemories),
          ]);
          hanggeAddition = buildMemoryPromptAddition(memories, fragments);
        }

        // 2. Standard memory prompt addition
        const memoryAddition = buildMemorySystemPromptAddition({
          availableTools: availableTools ?? new Set(),
          citationsMode,
        });

        // 3. Combine
        const combinedAdditions: string[] = [];
        if (memoryAddition) combinedAdditions.push(memoryAddition);
        if (hanggeAddition) combinedAdditions.push(hanggeAddition);

        // 4. Inject active task context
        const activeTasks = await getActiveTasks(config.apiUrl);
        if (activeTasks.length > 0) {
          const taskLines = activeTasks.map((t) => {
            const filled = Math.floor(t.progress / 10);
            const bar = "⬛".repeat(filled) + "⬜".repeat(10 - filled);
            return `- [${t.progress}%] ${t.title} (${t.priority}) ${bar}`;
          });
          combinedAdditions.push(
            `## 进行中的任务\n${taskLines.join("\n")}\n\n完成任务步骤后，调用 PUT /api/v1/tasks/{id}/progress 更新进度。中断的任务可用 POST /api/v1/tasks/{id}/resume 恢复。`
          );
        }

        // 5. Pass through
        return {
          messages,
          estimatedTokens: 0,
          systemPromptAddition: combinedAdditions.length > 0 ? combinedAdditions.join("\n\n") : undefined,
        };
      },

      // ── compact ───────────────────────────────────────────────────────
      async compact(params) {
        return delegateCompactionToRuntime(params);
      },

      // ── afterTurn ─────────────────────────────────────────────────────
      async afterTurn({ sessionId, messages }) {
        if (!config.skillMonitorEnabled) return;

        if (!sessionOperations.has(sessionId)) {
          sessionOperations.set(sessionId, []);
        }
        const ops = sessionOperations.get(sessionId)!;

        for (const msg of messages as unknown as ChatMessage[]) {
          if (msg.role === "user" && typeof msg.content === "string") {
            // User correction
            const correction = detectCorrection(msg.content, sessionId);
            if (correction) {
              await reportUserCorrection(config.apiUrl, sessionId, correction.original_action, correction.corrected_action, correction.context);
            }

            // Error in user message
            const error = detectError(msg.content);
            if (error) {
              await reportErrorRecovery(config.apiUrl, sessionId, error.error_type, error.error_message, ops.slice(-5));
            }

            // Task: Auto-extract multi-step plans
            if (detectMultiStepPlan(msg.content) && !currentTaskId.has(sessionId)) {
              const result = await autoExtractTask(config.apiUrl, msg.content, sessionId);
              if (result) {
                currentTaskId.set(sessionId, result.task_id);
                console.log(`[hangge-context] 📋 任务自动提取: ${result.task_id}`);
              }
            }
          }

          if (msg.role === "assistant") {
            // Tool calls
            const toolCalls = extractToolCalls(msg);
            if (toolCalls.length > 0) {
              ops.push(...toolCalls);
              lastAssistantAction.set(sessionId, toolCalls[toolCalls.length - 1].tool);
            }

            // ── Auto-create task from tool call sequence ──
            // 助手连续调≥2次工具，说明在执行多步骤工作，自动创建任务
            // 或者：隐式耗时估算≥5分钟，也自动创建
            const estimatedMinutes = estimateOperationTime(ops);
            const shouldCreateTask = (ops.length >= 2 || estimatedMinutes >= 5) && !currentTaskId.has(sessionId);
            if (shouldCreateTask) {
              const toolNames = ops.map(o => o.tool).filter(t => t).join(" → ");
              const taskTitle = estimatedMinutes >= 5
                ? `耗时任务 (~${estimatedMinutes}分钟): ${toolNames.slice(0, 50)}${toolNames.length > 50 ? "..." : ""}`
                : `自动检测: ${toolNames.slice(0, 80)}${toolNames.length > 80 ? "..." : ""}`;
              const result = await autoExtractTask(
                config.apiUrl,
                estimatedMinutes >= 5
                  ? `耗时操作 (~${estimatedMinutes}分钟): ${toolNames}`
                  : `执行多步骤操作: ${toolNames}`,
                sessionId,
                taskTitle
              );
              if (result) {
                currentTaskId.set(sessionId, result.task_id);
                console.log(`[hangge-context] 📋 任务自动创建: ${result.task_id} (${ops.length} ops, ~${estimatedMinutes}min)`);
              }
            }

            // ── Auto-create task from assistant plan detection ──
            // 助手消息里提到多步骤计划或耗时估计，自动创建任务
            if (typeof msg.content === "string" && !currentTaskId.has(sessionId)) {
              const plan = detectAssistantPlan(msg.content);
              if (plan) {
                console.log(`[hangge-context] 📋 助手计划检测: ${plan.title}`);
                const result = await autoExtractTask(
                  config.apiUrl,
                  plan.content,
                  sessionId,
                  plan.title
                );
                if (result) {
                  currentTaskId.set(sessionId, result.task_id);
                  console.log(`[hangge-context] 📋 助手计划任务创建: ${result.task_id}`);
                }
              }
            }

            if (typeof msg.content === "string") {
              // Error in assistant message
              const error = detectError(msg.content);
              if (error) {
                await reportErrorRecovery(config.apiUrl, sessionId, error.error_type, error.error_message, ops.slice(-5));

                // Task: Report error
                const tid = currentTaskId.get(sessionId);
                if (tid) {
                  await fetchJSON(`${config.apiUrl}/api/v1/tasks/${tid}/error?error_message=${encodeURIComponent(error.error_message.slice(0, 200))}`, { method: "POST" });
                }
              }

              // Task: Detect step completion
              const stepMsg = detectStepCompletion(msg.content);
              if (stepMsg) {
                const tid = currentTaskId.get(sessionId);
                if (tid) {
                  const task = await fetchJSON<{ completed_steps: number }>(`${config.apiUrl}/api/v1/tasks/${tid}`);
                  if (task) {
                    await updateTaskProgress(config.apiUrl, tid, task.completed_steps + 1, stepMsg);
                  }
                }
              }
            }
          }
        }

        // ── Report operation patterns to skill system ──
        // 改动1: 每轮结束都发操作序列（不再等ops.length>=5）
        if (ops.length >= 2) {
          await reportOperations(config.apiUrl, sessionId, ops, "command_sequence");
          // 保留最近操作用于上下文，避免无限增长
          sessionOperations.set(sessionId, ops.slice(-5));
        }
        if (ops.length > 30) {
          sessionOperations.set(sessionId, ops.slice(-15));
        }

        // ── 改动3: 检测手动触发技能生成的关键词 ──
        for (const msg of messages as unknown as ChatMessage[]) {
          if (msg.role === "user" && typeof msg.content === "string") {
            if (detectSkillSaveIntent(msg.content)) {
              console.log(`[hangge-context] 🎯 检测到技能保存意图`);
              await triggerManualSkillGeneration(config.apiUrl, sessionId, ops);
            }
          }
        }
      },

      // ── dispose ───────────────────────────────────────────────────────
      dispose() {
        sessionOperations.clear();
        lastAssistantAction.clear();
        currentTaskId.clear();
      },
    }));
  },
});
