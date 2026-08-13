# DeepSeek, Usage, and Authentication Restoration Design

Date: 2026-08-13

Status: Approved

Baseline: `main` at `d961483`

## Objective

Restore four user-approved capabilities that exist only on an abandoned development line,
while adapting them to the current Ductor v0.20.1 architecture:

1. DeepSeek models through the Anthropic-compatible endpoint and Claude CLI;
2. a transport-independent `/usage` command for DeepSeek, Claude Code, and Codex;
3. main-agent-only Claude OAuth login-token keepalive; and
4. reliable synchronization of each sub-agent's chat authorization settings.

This is a semantic reimplementation against the current codebase. The implementation may use
the abandoned branch as behavioral and test reference, but it must not cherry-pick that branch
or reintroduce its obsolete architecture.

## Scope

### In scope

- DeepSeek as an independently selectable logical provider;
- a DeepSeek session bucket isolated from native Claude sessions;
- DeepSeek configuration hot reload, except for its secret;
- Ductor-owned DeepSeek balance snapshots;
- `/usage` through every enabled messenger/API command path;
- localized output for all currently shipped languages;
- Claude OAuth login-token keepalive;
- sub-agent chat authorization seeding and synchronization;
- tests for the new behavior and regressions across existing providers and transports.

### Out of scope

- any new Docker rebuild feature, hardening, validation, lock, smoke-check matrix, or refactor;
- changes to Docker users, `sudo`, root access, images, containers, or mounts;
- TaskHub restoration;
- the fork sentinel version `0.999.0+icamelot`;
- ComfyUI work;
- changes to the personal-assistant skill or its files;
- automatic merge or publication without the user's explicit post-verification approval.

## Compatibility Contract

The existing Docker implementation is not part of this change. The following accepted behavior
must remain intact and covered by the existing regression suite:

- concrete Claude, Codex, and Gemini CLI version resolution during image rebuild;
- cached development, Office, PDF, and OCR tool layers;
- configured Docker extras;
- the shared main/sub-agent sandbox image;
- candidate-first image build and verification;
- immutable-image promotion, existing rollback behavior, and nonzero rebuild failures;
- per-agent environment injection;
- Docker init and configured container startup commands.

The work must also preserve current Claude, Codex, Gemini, Antigravity, Grok, model selector,
reasoning-effort, session, messenger, and service behavior unless this design explicitly changes
it.

## Chosen Architecture

Implement the restored behavior using the current architecture rather than transplanting old
commits. Five bounded units connect through existing Ductor interfaces:

1. a DeepSeek logical-provider adapter that delegates execution to Claude CLI;
2. a provider-neutral usage service with separate provider clients;
3. a Ductor-owned DeepSeek balance snapshot repository and observer;
4. a Claude OAuth token keepalive observer; and
5. a sub-agent configuration synchronization step in the supervisor.

The units must expose typed, testable interfaces. Network clients return structured success or
failure results; presentation code never parses raw provider responses. Persistent-state code
owns validation, retention, and atomic writes; observers own only scheduling and lifecycle.

## DeepSeek Configuration and Secrets

Add a non-secret `deepseek` section to `AgentConfig` and the generated configuration defaults:

```json
{
  "deepseek": {
    "enabled": false,
    "base_url": "https://api.deepseek.com/anthropic",
    "models": ["deepseek-v4-pro", "deepseek-v4-flash"]
  }
}
```

The API key is never stored in `config.json`. It is read only from the main Ductor home's `.env`:

```dotenv
DEEPSEEK_API_KEY=...
```

For the default installation this is `~/.ductor/.env`; when `DUCTOR_HOME` is explicitly set, it
means that root's `.env`. Sub-agents use the same root secret instead of copying it into their
own configuration files.

Rules:

- `enabled`, `base_url`, and `models` use the existing config deep-merge and hot-reload path.
- Model IDs are trimmed, limited to 256 characters, must contain no whitespace, control
  characters, or NUL bytes, and must be unique after trimming.
- `base_url` must be an absolute HTTPS URL. A non-HTTPS endpoint is permitted only for an
  explicitly local loopback address in tests or local development; malformed values disable
  DeepSeek with a sanitized diagnostic.
- The API key is loaded through the existing secret-loading boundary and never appears in normal
  config persistence, provider metadata, status output, exceptions, or logs.
- `.env` changes require a Ductor restart. Config hot reload must never rewrite `.env`.

## DeepSeek Availability and Model Selection

DeepSeek is a distinct logical provider named `deepseek`. It is available only when all of these
conditions hold:

- `deepseek.enabled` is true;
- at least one configured DeepSeek model is valid;
- `DEEPSEEK_API_KEY` is present; and
- the Claude CLI executable is installed and runnable.

Claude OAuth authentication is not a DeepSeek availability requirement. Provider discovery must
therefore distinguish "Claude CLI executable is available" from "native Claude account is
authenticated."

`/model` displays a separate `DEEPSEEK` provider button and lists the configured models beneath
it. DeepSeek does not appear inside the native Claude model list. Direct `/model <name>` selection
uses the same validation and availability rules as the interactive selector.

The provider registry reports DeepSeek as its own provider and associates its configured model
IDs with it. Duplicate model IDs across logical providers are rejected as invalid configuration
rather than resolved by ordering.

## Logical Provider Versus Execution Adapter

The session and user-facing provider is `deepseek`; the process implementation is the existing
Claude CLI adapter. This distinction must be explicit rather than making DeepSeek masquerade as
Claude in `ModelRegistry.provider_for()`.

For a DeepSeek turn, the delegated Claude CLI process receives:

- `ANTHROPIC_BASE_URL` from `deepseek.base_url`; and
- `ANTHROPIC_AUTH_TOKEN` from `DEEPSEEK_API_KEY`.

The overrides apply to that invocation only and take precedence over inherited host variables,
the main agent `.env`, a sub-agent `.env`, and generic provider environment values. Host and
Docker execution must follow the same precedence.

For every native Claude turn, Ductor must add no DeepSeek-derived override to the child process.
Switching away from DeepSeek cannot leave invocation-local values behind. Pre-existing native
Claude environment behavior remains unchanged, including an endpoint deliberately configured by
the user outside the `deepseek` section.

No provider secret or full constructed command may be logged.

## Session Isolation

DeepSeek uses `provider_sessions["deepseek"]`; native Claude continues to use
`provider_sessions["claude"]`.

All session-sensitive paths must resolve the logical provider bucket, including:

- normal and streaming turns;
- model switching and switch-back resume hints;
- `/new` and `/reset`;
- timeout preservation;
- invalid-resume and process-error cleanup;
- message, token, and cost accounting;
- topic-specific model selection;
- memory-flush and continuation behavior where a provider session ID is used.

Switching between native Claude and DeepSeek preserves both buckets and resumes only the target
bucket. A session ID from either bucket must never be passed to the other endpoint.

Configured DeepSeek models share the one `deepseek` bucket, matching Ductor's existing rule that
models within a logical provider share provider history. No migration copies an existing Claude
session into DeepSeek. After upgrade, the first DeepSeek turn starts a new DeepSeek session;
existing Claude history remains available when switching back.

## Usage Service

Add a provider-neutral usage service with three independent clients:

- DeepSeek balance;
- Claude Code subscription usage; and
- Codex subscription usage.

Each client returns a typed result containing either normalized data or a bounded error category.
Expected error categories include disabled, not configured, not logged in, expired, rate limited,
timeout, malformed response, and unavailable. Raw response bodies, credentials, and request
headers are not part of returned errors.

The provider clients use the same read-only endpoints and credential stores as the abandoned
implementation, adapted behind the new interfaces:

- DeepSeek derives `<configured-scheme>://<configured-authority>/user/balance` from
  `deepseek.base_url` and
  authenticates with `DEEPSEEK_API_KEY`;
- Claude reads the OAuth login record from `~/.claude/.credentials.json` and queries the Claude
  subscription usage endpoint; and
- Codex honors `CODEX_HOME` (falling back to `~/.codex`), reads `auth.json`, and queries the Codex
  subscription usage endpoint with its account identifier when present.

Each request has a 10-second total timeout. HTTP 401 and 403 map to expired or unauthenticated as
appropriate, HTTP 429 maps to rate limited, and other non-success responses map to unavailable
without exposing their bodies.

`/usage` starts all three queries concurrently. Each query has an independent timeout and failure
boundary. One provider's failure must not cancel or hide another provider's result. Unexpected
internal exceptions are converted to that provider's generic unavailable result and logged
without sensitive values.

### Command integration

`/usage` is registered in the orchestrator's shared command registry and messenger command
classification so every enabled command-capable path uses the same implementation, including
Telegram, Matrix, Slack, and the direct API path. Telegram additionally registers `/usage` in its
translated bot-command menu and recognizes it through the existing middleware path.

The command always renders all three provider sections:

- DeepSeek: current balance and today's spend or recharge;
- Claude Code: plan, 5-hour usage, 7-day usage, and reset times;
- Codex: plan, short-window usage, 7-day usage, and reset times.

Unavailable sections show a short localized status instead of disappearing. Percentages and
monetary values are normalized before formatting. Reset timestamps are converted to
`user_timezone`. Codex windows are classified by their duration, not response-map position, so a
missing short window cannot cause the weekly window to be mislabeled.

All labels and error states are added to every currently shipped locale: `de`, `en`, `es`, `fr`,
`id`, `nl`, `pt`, and `ru`. The active locale determines output; provider-facing code contains no
hard-coded Chinese presentation strings. This work does not change Ductor's global default
language or add a partial locale: the existing configured language and English fallback remain
authoritative.

## DeepSeek Balance Snapshots

### Ownership and path

Ductor owns a versioned snapshot file exposed through `DuctorPaths`, named
`deepseek_balance_snapshots.json` under the root Ductor home. Only the main agent writes it.
Sub-agents and `/usage` access the main root path, never an agent-local copy. A `/usage` command
handled by a sub-agent can read snapshot history but cannot append to it.

The repository stores decimal monetary values as strings to avoid binary floating-point drift.
A versioned document contains an import marker and timestamped snapshots. Each snapshot contains
one or more normalized currency balances when the provider returns them:

```json
{
  "version": 1,
  "legacy_import_completed": true,
  "snapshots": [
    {
      "captured_at": "2026-08-13T01:00:00Z",
      "balances": [{"currency": "CNY", "total": "123.45"}]
    }
  ]
}
```

Unknown, malformed, negative-precision, or non-finite monetary values are rejected. Consumption
is calculated only between balances with the same normalized currency. The formatter uses the
currency returned by DeepSeek rather than assuming CNY.

### Observer lifecycle

A `DeepSeekBalanceObserver` runs only for the main agent and only when DeepSeek is enabled and a
key is present. It:

1. attempts one collection after observer startup;
2. repeats every 30 minutes;
3. validates and appends successful samples;
4. removes records older than 35 days; and
5. stops through the existing observer cancellation lifecycle.

Failures skip that sample and do not stop Ductor. The observer does not write empty or partially
validated samples. Appends, pruning, and migration are serialized by one repository lock shared
by every repository instance for the same canonical path, then saved with the existing
atomic-state pattern. Sampling timestamps are UTC. A new result is not appended when the latest
stored snapshot is less than 30 minutes old and contains the same normalized currency balances;
a changed balance is retained even inside that interval.

Changing `deepseek.enabled` through hot reload starts or stops collection without requiring a
service restart. Key changes still require restart because secrets are not hot reloaded.

### Today's spend

For each currency, today's baseline is selected using `user_timezone`:

1. the earliest valid snapshot at or after local midnight; otherwise
2. the latest valid snapshot before local midnight.

Today's spend is `baseline - current`; a negative result is displayed as a recharge. A missing
same-currency baseline yields current balance without a fabricated spend value. The 30-minute
sampling interval means the baseline is approximate by up to roughly one interval.

A successful `/usage` DeepSeek query handled by the main agent submits its normalized result to the
same repository and uses the same serialization, validation, retention, and deduplication rules
as the observer. A sub-agent query remains read-only.

### One-time legacy import

On first repository initialization, Ductor attempts to read the personal-assistant skill's existing
`.balance_snapshots.json` from the main workspace. Valid records are normalized, deduplicated,
and imported before the new snapshot is appended. Legacy records that contain only a balance are
interpreted as CNY because the previous integration rendered them as yuan. Import is best effort
and records a completion marker even when the legacy file is missing, empty, or malformed,
preventing repeated work.

The legacy file is never written, renamed, or deleted. After initialization, Ductor never reads
it again and `/usage` has no runtime dependency on personal-assistant.

## Claude OAuth Login-Token Keepalive

Add `claude_token_keepalive: true` to `AgentConfig`. One in-process asyncio observer runs only for
the main agent. Sub-agents must never start their own refresher because Claude refresh tokens can
rotate and concurrent refreshes may invalidate each other.

The observer manages only the OAuth login record in `~/.claude/.credentials.json`. It does not
manage Claude setup tokens, Anthropic API keys, or the DeepSeek key.

Behavior:

- inspect credentials every 30 minutes;
- send a refresh request only when the access token expires within two hours;
- enforce at least four hours between refresh attempts within the running process;
- make no request when the credential structure or refresh token is missing;
- preserve unknown top-level and OAuth fields;
- update only valid token fields returned by a successful refresh response;
- write through a same-directory temporary file with mode `0600` and atomic replacement;
- leave the original file untouched on HTTP, timeout, parse, validation, or write failure;
- continue the observer after all non-cancellation failures.

Before replacing the file, the writer must confirm that the current on-disk refresh token still
matches the token used for the request. If the Claude CLI or another process changed credentials
during the network call, the observer discards its response instead of overwriting newer data.

Logs contain only sanitized result categories. They never contain tokens, full response bodies,
or sensitive request data.

`/usage` does not trigger or await a refresh. It reads credentials independently and reports an
expired Claude login when appropriate. Atomic credential replacement makes concurrent reads safe.

## Sub-Agent Chat Authorization Synchronization

`agents.json` is authoritative for each sub-agent's chat access configuration. Whenever a
sub-agent is first created or rebuilt in-process, the supervisor resolves that sub-agent's final
runtime configuration and synchronizes these exact values into its `config.json` before its
config-reload observer can act:

- `allowed_user_ids`;
- `allowed_group_ids`; and
- `group_mention_only`.

The existing synchronization of `provider`, `model`, and `reasoning_effort` remains. Lists and
booleans must be written even when they are empty or false; truthiness filtering would leave stale
or placeholder values on disk. The write uses the existing atomic config updater and preserves
unrelated fields.

The supervisor writes the values produced by `merge_sub_agent_config`. It does not implicitly
inherit the main agent's allowlists. This makes the on-disk hot-reload source match the actual
sub-agent runtime configuration and prevents later `/model` writes or restarts from restoring
template placeholder IDs.

If authorization synchronization fails, that sub-agent does not start. The supervisor records a
sanitized error and continues running the main agent and other sub-agents. No access-list values
are logged.

This synchronization has no relationship to Docker identity or privilege. It must not change the
container user, `sudo`, root access, image, command, or environment behavior.

## Error Handling and Security

- Every external usage or refresh request has a finite timeout.
- Network failures never terminate the Ductor service.
- Provider failures are represented by bounded categories at presentation boundaries.
- Secrets, authorization headers, raw response bodies, and full secret-bearing command lines are
  never logged or returned to users.
- Persistent JSON is schema-validated on read and atomically replaced on write.
- A malformed snapshot file is treated as unavailable state, not partially trusted input. The
  implementation preserves or quarantines evidence according to the existing state-file pattern
  rather than silently emitting guessed records.
- Observer tasks propagate cancellation and suppress ordinary iteration failures.
- DeepSeek and Claude environment separation is tested in both directions.

## Testing Strategy

Implementation follows test-driven development. Each behavior begins with a focused failing test,
then the minimum implementation, followed by focused and regression verification.

### DeepSeek tests

- config defaults, validation, secret separation, and hot reload;
- provider availability with DeepSeek key but no Claude OAuth login;
- unavailable state when the Claude executable or required config is missing;
- independent provider registry and `/model` presentation;
- direct model selection validation;
- host and Docker environment injection precedence;
- native Claude invocations never receiving DeepSeek overrides;
- logical-provider-to-Claude-executor delegation;
- Claude/DeepSeek session-ID isolation across normal, streaming, reset, timeout, error, topic, and
  switch-back flows;
- multiple DeepSeek models sharing only the DeepSeek bucket.

### Usage and snapshot tests

- concurrent queries and independent timeouts;
- full success, partial success, and full failure rendering;
- disabled, unconfigured, unauthenticated, expired, limited, malformed, and network-error states;
- Claude and Codex credential parsing without disclosure;
- Codex rate-window classification by duration;
- timezone conversion and reset-time formatting;
- command registration and dispatch through all supported transport paths;
- translations present for all shipped locales;
- startup and 30-minute observer scheduling with a controlled clock;
- snapshot schema validation, decimal round-tripping, atomic writes, deduplication, and 35-day
  retention;
- same-currency local-midnight baseline selection and recharge calculation;
- `/usage` and observer writes sharing one repository boundary;
- one-time legacy import, missing/malformed legacy input, and no legacy mutation;
- disabled or unconfigured DeepSeek causing no observer network call.

### Keepalive tests

- main-agent-only lifecycle and default-enabled configuration;
- no request when credentials or refresh token are absent;
- refresh timing and four-hour attempt spacing;
- valid response application while preserving unknown fields;
- on-disk compare-before-replace behavior under concurrent credential rotation;
- same-directory atomic replacement and final `0600` permissions;
- HTTP, timeout, malformed response, missing access token, and write failures preserving the
  original credentials;
- cancellation and observer shutdown.

### Sub-agent tests

- exact user/group/mention values seeded before reload can observe them;
- empty lists and false values overwrite stale data;
- no implicit inheritance from main-agent allowlists;
- unrelated config fields remain unchanged;
- subsequent model writes and hot reload cannot restore placeholders;
- synchronization failure prevents only the affected sub-agent from starting;
- Docker configuration and privilege fields remain untouched.

### Regression verification

Run, at minimum:

1. focused tests for every changed subsystem;
2. the complete pytest suite;
3. Ruff formatting verification and lint checks;
4. strict mypy checks;
5. existing provider, selector, session, messenger, supervisor, observer, and Docker tests.

Authentication failures for Gemini, Claude, Grok, or other CLIs during environment-dependent
operational probes are reported but are not treated as implementation failures when the user has
not logged those CLIs in. Unit and integration tests must not require live provider credentials.

## Acceptance Criteria

The work is accepted only when all of these statements are demonstrated:

1. DeepSeek can be selected and used with `DEEPSEEK_API_KEY` and a Claude CLI installation even
   when native Claude OAuth is not logged in.
2. Native Claude and DeepSeek never exchange or overwrite session IDs, and switching back resumes
   the correct provider history.
3. Native Claude child processes never receive DeepSeek-derived endpoint overrides.
4. `/usage` returns all three sections and preserves successful results when another provider
   fails.
5. Ductor calculates DeepSeek daily spend without requiring personal-assistant after a one-time
   optional import.
6. Snapshot collection starts only once in the main agent, samples on the approved interval, and
   retains no more than 35 days.
7. Claude credential-refresh failures do not stop Ductor or damage credentials.
8. Sub-agent config writes and hot reload preserve the correct per-agent chat authorization.
9. All shipped locales contain the new command and output strings.
10. The complete automated quality gates pass, subject only to explicitly documented
    credential-gated operational probes.
11. Existing accepted Docker and provider behavior remains unchanged.
12. TaskHub, obsolete Docker hardening, and unrelated abandoned-branch content are not restored.

## Implementation and Release Gates

Implementation occurs on an isolated feature branch/worktree created from the approved `main`
baseline. The later implementation plan must divide the four feature domains into reviewable,
test-driven commits and include integration checkpoints for the shared configuration, lifecycle,
and session changes.

After implementation:

1. run all verification defined above and inspect the actual command results;
2. perform a code review and resolve accepted findings;
3. provide the user with the complete feature list, changed behavior, test results, known limits,
   and exact proposed integration target;
4. stop and request the user's explicit approval to publish;
5. only after approval, merge the feature branch into local `main` without discarding unrelated
   user work;
6. verify the merged `main` again as appropriate; and
7. push local `main` to the user's `origin` remote repository.

Neither merge nor push is authorized merely by approval of this design or implementation plan.
They require the explicit post-verification user confirmation described in step 4. Deployment,
package reinstallation, service restart, and live credential-dependent probes are also separate
operational actions and must not be inferred from permission to merge and push.
