# Subagent Dispatch Runtime Playbook

Use this playbook only as 若命, or when 若命 explicitly asks another role to inspect dispatch rules.

## Runtime Rule

You must treat subagents as runtime execution units bound to approved project identities. They are not new personas.

Runtime nicknames are transport metadata only. Never write them as project identities in inbox, summaries, review reports, QA reports, or user-facing conclusions.

## Authorized Child Identities

Validate against `docs/collaboration/agent-registry.json` before every child identity binding.

| agentKey | Display | Identity file | Default lifecycle |
|---|---|---|---|
| `tingyun` | 听云 | `docs/collaboration/roles/tingyun.md` | persistent by engineering work line; reset for unrelated work or dirty context |
| `guanzhi` | 观止 | `docs/collaboration/roles/guanzhi.md` | persistent by QA gate/rerun; reset for unrelated QA or independent judgment |
| `jinghua` | 镜花 | `docs/collaboration/roles/jinghua.md` | persistent by review gate; reset for unrelated review or independent second look |
| `qingqiu` | 清秋 | `docs/collaboration/roles/qingqiu.md` | persistent by UX/IA review node; reset for unrelated page or flow |
| `shuangxian` | 霜弦 | `docs/collaboration/roles/shuangxian.md` | persistent by data/ops review node; reset for unrelated rule topic |

`ruoming/若命` is the controller. 若命 must not create 若命 as a child agent.

Do not add, rename, replace, or alias identities without explicit user approval and synchronized updates to:

- `docs/collaboration/agent-registry.json`
- `docs/collaboration.md`
- `docs/collaboration/roles/*.md`
- this playbook

## Header Validation

Every role file must start with YAML frontmatter.

Before dispatch, validate that the role header matches the registry for:

- `agentKey`
- `display`
- `role_type`
- `identity_file`
- `can_spawn_subagents`
- `allowed_spawns`
- `can_reset_subagents`
- `can_close_subagents`
- `code_write_permission`
- `docs_write_permission`
- `commit_push_permission`
- `external_side_effect_permission`
- `default_lifecycle`
- `output_contracts`
- `required_init_files`

Only `ruoming` may have:

- `can_spawn_subagents: true`
- non-empty `allowed_spawns`
- `can_reset_subagents: true`
- `can_close_subagents: true`

If validation fails, do not dispatch. Return or record:

```text
IDENTITY_BLOCKED: role=<Display>, agentKey=<agentKey>, reason=<reason>
```

## Identity Pool

If runtime supports persistent child sessions, 若命 may initialize all approved child identities at project startup.

Initialization grants identity only. It does not grant task permission.

Each child must read:

- `docs/collaboration.md`
- its own `docs/collaboration/roles/<agentKey>.md`
- any dispatch packet fact sources

Each child must answer first with:

```text
IDENTITY_READY: role=<Display>, agentKey=<agentKey>, files_read=[docs/collaboration.md, docs/collaboration/roles/<agentKey>.md]
```

If it cannot satisfy identity binding, it must answer `IDENTITY_BLOCKED`.

## Dispatch Authorization

Before every task dispatch, 若命 must validate:

- role is in the registry
- identity file exists
- header matches registry
- task belongs to role responsibility
- task does not exceed role permissions
- write scope is explicit
- verification scope is explicit
- external side effects are none or explicitly listed
- stop condition is explicit
- lifecycle instruction is explicit

If any item fails, do not dispatch.

## Parallelism And Independence

Dispatch agents in parallel only when their scopes do not share write targets, mutable state, external side effects, or review independence requirements.

Do not run implementation and review on the same uncommitted moving target unless the review packet pins the diff or file set.

For independent review/QA, prefer reset or fresh identity context when prior discussion could bias the result.

## Result Acceptance

若命 must inspect every child result before using it.

Accept a child result only when it includes:

- formal role and `agentKey`
- scope actually covered
- files read/changed
- evidence
- unverified scope
- residual risk
- requested next action

If the result exceeds permission, uses runtime nickname as identity, lacks evidence, or changes scope, treat it as `REQUEST` or `BLOCKED`, not as a gate result.

## Dispatch Packet

Use this exact structure for a new child task:

```text
你是 <Display>，agentKey=<agentKey>。这是项目授权身份，不使用运行时昵称作为项目身份。

Identity initialization:
- Must read: docs/collaboration.md
- Must read: docs/collaboration/roles/<agentKey>.md
- Must validate role YAML header against docs/collaboration/agent-registry.json.
- If identity binding fails, reply:
  IDENTITY_BLOCKED: role=<Display>, agentKey=<agentKey>, reason=<reason>
- If identity binding succeeds, first line must be:
  IDENTITY_READY: role=<Display>, agentKey=<agentKey>, files_read=[docs/collaboration.md, docs/collaboration/roles/<agentKey>.md]

Task:
- Objective:
- Scope:
- Forbidden scope:
- Fact sources:
- Files you may read:
- Files you may change, or READ ONLY:
- Verification allowed:
- External side effects allowed:
- Output format:
- Stop condition:
- Lifecycle:

If identity, permission, scope, fact source, or validation path is unclear, reply REQUEST/BLOCKED. Do not guess.
```

## Follow-Up Packet

Use this structure for same-role same-node continuation:

```text
继续以 <Display>，agentKey=<agentKey> 执行。不要使用运行时昵称作为项目身份。

Current task:
- Objective:
- Scope:
- Forbidden scope:
- Fact sources:
- Files you may read:
- Files you may change, or READ ONLY:
- Verification allowed:
- External side effects allowed:
- Output format:
- Stop condition:
- Lifecycle:
```

Follow-up does not expand permission. If the task changes role, scope, gate, or authorization, reset or create a new approved identity.

## Reset Scale

Default: keep identities alive and reuse same-node context.

Reset when any condition is true:

- role changes
- objective or gate changes
- task moves to unrelated PRD/stage/sample/path
- review or QA needs independent judgment
- context is stale, contradictory, polluted, or too large
- permission, write scope, external side effects, or fact sources change
- previous node reached `DONE_CLAIMED`, `PASS`, `NEEDS_FIX`, `BLOCKED`, or `REQUEST` and no same-scope follow-up is needed

Close only when:

- runtime cannot reset
- identity is blocked
- runtime is unavailable
- user requests shutdown
- security requires cutting context

## Lifecycle Records

Record formal identity only, never runtime nickname:

```text
SUBAGENT_OPENED
- role:
- agentKey:
- identity_files:
- objective:
- lifecycle:
- write_permission:
- verification_permission:

SUBAGENT_RESET
- role:
- agentKey:
- reason:
- new_scope:

SUBAGENT_RESULT
- role:
- agentKey:
- status:
- evidence:
- files_changed_or_read:
- residual_risk:

SUBAGENT_CLOSED
- role:
- agentKey:
- reason:
- next_action:
```

Write records to inbox or reports only when the subagent affects project gates, risk, delivery status, or user-visible conclusions.

## Context Budget

Give child agents only:

- current objective
- formal identity
- exact REQUEST/PRD excerpt
- relevant paths
- necessary `git status` facts
- allowed commands
- stop condition

Do not paste full inbox, full chat history, long logs, large generated data, or unrelated role docs.

## Runtime Nickname Ban

Forbidden in project-visible records:

- `Spawned Bacon to review...`
- `Cicero said PASS`
- `Fermat will implement`
- `Reviewer agent approved`

Required style:

- `镜花 CODE_REVIEW: PASS`
- `听云 DONE_CLAIMED`
- `观止 QA: NEEDS_FIX`
