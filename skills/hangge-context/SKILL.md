# Hangge Context Engine Plugin v3

> Native OpenClaw Context Engine plugin (TypeScript), integrating Hangge Assistant memory system + skill auto-generation

## Architecture

This is a **native OpenClaw plugin** (not a Python skill). It registers via `api.registerContextEngine()` in `definePluginEntry`, implementing the full Context Engine lifecycle:

| Lifecycle | Purpose |
|-----------|---------|
| `ingest()` | Message indexing (currently no-op, pattern detection in afterTurn) |
| `assemble()` | Query Hangge memories + inject into `systemPromptAddition` |
| `compact()` | Delegate to OpenClaw built-in compaction (`ownsCompaction: false`) |
| `afterTurn()` | Tool call monitoring, error recovery detection, user correction detection |

## Features

### Memory Query (assemble)
- Queries Hangge Assistant memory and context APIs
- Injects relevant memories into `systemPromptAddition`
- Combines with OpenClaw's built-in memory prompt via `buildMemorySystemPromptAddition()`

### Tool Call Monitoring (afterTurn)
- Monitors assistant tool call sequences
- Detects error recovery patterns → triggers skill auto-generation
- Detects user correction patterns → triggers skill auto-generation
- Command sequence ≥5 → triggers skill auto-generation

## Configuration

In `openclaw.json`:

```json5
{
  plugins: {
    slots: {
      contextEngine: "hangge-context"
    },
    entries: {
      "hangge-context": {
        enabled: true,
        config: {
          apiUrl: "http://localhost:8000",
          maxMemories: 5,
          minRelevance: 0.3,
          skillMonitorEnabled: true
        }
      }
    }
  }
}
```

## Trigger Mechanism

| Pattern Type | Trigger | Description |
|-------------|---------|-------------|
| Error Recovery | Immediate | RuntimeError/ModuleNotFoundError/FileNotFoundError/PermissionError/CommandFailed/TypeError |
| User Correction | Immediate | "不对"/"应该是"/"错了"/"No"/"Wrong"/"Actually" |
| Command Sequence | ≥5 tool calls | After 5 consecutive tool calls |

## API Dependencies

- `GET /api/v1/memories/search` - Memory search
- `POST /api/v1/context/query` - Context query
- `POST /api/v1/skills/trigger/operations` - Operation sequence trigger
- `POST /api/v1/skills/trigger/error-recovery` - Error recovery trigger
- `POST /api/v1/skills/trigger/user-correction` - User correction trigger

## Build

```bash
cd ~/.agents/skills/hangge-context
npm install   # install devDependencies (typescript)
npm run build # compile src/index.ts → dist/index.js
```

## Developer

- Author: 旺财
- Version: 3.0.0 (native TypeScript rewrite)
- Updated: 2026-04-15
