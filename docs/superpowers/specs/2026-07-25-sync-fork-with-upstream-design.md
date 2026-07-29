# Sync Fork with Upstream Design

Date: 2026-07-25

Status: Approved

Branch: `chore/sync-upstream-2026-07-25`

Planning worktree:
`/home/zqxu/ductor/.worktrees/sync-upstream-2026-07-25`

## Objective

Synchronize the fork with the investigated official Ductor upstream while
preserving the fork's already accepted Docker rebuild behavior.

The synchronization will use an ordinary merge of the locked upstream commit
into a branch descended from the locked local `main`. It will not rewrite or
reselect the existing local commits.

This design governs a later execution session. The planning session creates only
the design, implementation plan, and execution prompt. It does not merge
upstream or modify production code.

## Locked Baseline

All implementation and verification must use these immutable commits:

- local `main`: `d1167a016eaddc779ecd3f7d70c077832b22a4eb`
- `origin/main`: `d1167a016eaddc779ecd3f7d70c077832b22a4eb`
- official `upstream/main`: `3e3c88af57bc094105e73cd24673075e076591ab`
- merge-base: `626d90bdbe3b4404b8e4795610ee52f368177457`

At the final pre-planning fetch, local `main` had 20 commits not in upstream and
upstream had 104 commits not in local `main`. Official tags after the merge-base
and reachable from the locked upstream commit were:

- `v0.19.0`
- `v0.20.0`
- `v0.20.1`

The execution session must verify the branch still descends from the locked local
commit and that the upstream object is present before making changes. It must not
silently replace either commit with a moving branch name.

## Chosen Synchronization Strategy

Use Plan A:

1. Work only in the existing planning worktree and branch.
2. Establish a test baseline for the local behavior contracts.
3. Add missing characterization tests before the merge when a protected local
   behavior lacks reliable coverage.
4. Perform an ordinary merge of the exact upstream commit
   `3e3c88af57bc094105e73cd24673075e076591ab`.
5. Resolve conflicts by behavior, not by retaining an entire side's file.
6. Verify both the upstream changes and the protected local behavior.
7. Stop on the synchronization branch and wait for approval.

The execution must not:

- rebase;
- squash;
- cherry-pick or reselect the existing local Docker commits;
- use whole-file `ours` or `theirs` conflict resolution;
- merge the result back to local `main`;
- push to `origin`;
- create a pull request.

No evidence found during investigation makes Plan A unsafe or infeasible. If new
evidence shows that an ordinary merge cannot preserve both sides' required
behavior, the execution session must stop and request a new decision instead of
switching strategies.

## Local Capability Preservation Contract

Preservation is defined by observable behavior and tests, not by keeping the old
implementation text.

| Capability | Required post-merge behavior | Verification focus |
|---|---|---|
| Dynamic provider versions | Rebuild resolves concrete Claude, Codex, and Gemini CLI versions from npm and propagates them as build inputs | resolver parsing, validation, and build-argument tests |
| Candidate-first build | A unique candidate tag is built and verified before the production tag or running runtime is changed | event ordering and failure-boundary tests |
| Immutable promotion | Promotion and container updates use the verified immutable image ID | image inspection, tagging, and update-state tests |
| Shared image | The main agent and Docker sub-agents use the same configured shared image | configuration and target-selection tests |
| BuildKit caching | Normal cache behavior remains enabled; no global `--no-cache` is added | generated build-command assertions |
| Tool layer order | Development, Office, PDF, and OCR layers remain before provider CLI installation | generated Dockerfile ordering tests |
| Docker extras | Every configured `docker.extras` entry remains included | extras resolution and generated Dockerfile tests |
| Python-only Playwright | The Python package remains available without Chromium, `playwright install`, browser profiles, caches, or mounts | positive package and negative instruction tests |
| Failure semantics | Rebuild failures return nonzero and preserve the approved safe external reporting behavior | CLI exit and sanitized error tests |
| Build diagnostic suppression | The local `_exec_stream()` build path does not expose raw subprocess diagnostics | focused logging/output tests |

Before merging, the execution session must map each row to existing tests. A row
without reliable coverage requires a characterization test that passes against
the locked local implementation. After the merge, the same contract must pass
through the upstream interfaces.

## Conflict Resolution Rule: C1-R

For every overlapping region:

1. Identify the behavior introduced by upstream from its code, tests, or
   documentation.
2. Identify the protected local behavior and its test.
3. Accept the upstream structure and public interface by default.
4. Adapt the local behavior to that structure.
5. Run both sides' focused tests.
6. Record any intentional non-adoption of upstream behavior.
7. Stop for user direction if both behaviors cannot coexist.

The merge must not be declared successful merely because Git reports no
unresolved text conflicts. Semantic conflicts must be checked separately.

## Known Overlap Surface

Only four files were modified by both sides between the merge-base and the
locked tips:

### `ductor_bot/cli/base.py`

Combine:

- upstream task ID propagation, prompt temporary-file support, and safe command
  formatting;
- local Docker environment precedence:
  main agent `.env` < sub-agent `.env` < provider `extra_env`;
- unconditional explicit environment injection into the container, because the
  containerized process does not inherit the host process environment.

The merged path must use upstream command-log redaction without dropping the
local main/sub-agent environment behavior.

### `ductor_bot/cli_commands/docker.py`

Combine:

- the local candidate build, verification, immutable promotion, shared-container
  update, recovery, and nonzero failure behavior;
- upstream's `docker.extras` dependency-resolution refactor.

The old upstream "remove now and rebuild later" behavior must not replace the
accepted local candidate-first rebuild workflow.

### `ductor_bot/infra/docker.py`

Combine:

- local concrete provider version resolution and build arguments;
- local safe build-output suppression;
- local unconditional agent `.env` injection;
- upstream environment-value redaction for Docker command logs.

The merge must retain normal BuildKit caching and the generated Dockerfile layer
contract.

### `tests/cli/test_env_injection.py`

Keep both:

- upstream task ID and environment-path coverage;
- local host/main/sub-agent/provider environment precedence coverage.

If test hunks conflict textually, split or reorganize tests without deleting
either behavior contract.

The remaining upstream-only files are accepted normally. The remaining
local-only Docker implementation and tests remain present, subject to semantic
verification against changed upstream interfaces.

## Configuration Strategy: M2-U

Adopt upstream's existing configuration behavior without a fork-specific
migration layer:

1. Load the existing `config.json`.
2. Build current defaults from `AgentConfig`.
3. Recursively add missing fields.
4. Preserve existing user values.
5. Atomically write the expanded configuration only when it changed.
6. Preserve upstream exclusions for special fields such as the beta API
   configuration.

The Git synchronization itself must not read and rewrite the user's real
configuration. Tests must use temporary configuration fixtures.

After the synchronized Ductor is eventually started by the user, upstream's
normal `load_config()` behavior may explicitly add new optional settings such as
Slack, Grok, project roots, and cron controls to the real configuration. That is
accepted upstream runtime behavior, not a migration performed by the execution
session.

## Persistent Runtime Data

Do not proactively rewrite:

- `sessions.json`;
- `named_sessions.json`;
- `tasks.json`;
- cron or webhook state;
- other files under the user's Ductor home.

Upstream's scoped inter-agent session names are accepted for new sessions.
Legacy `ia-<sender>` entries remain supported by upstream and must be covered by
old-format fixture tests. No one-time session migration script is required.

## Logging Decision: L3

Adopt upstream's environment-value redaction. Preserve the fork's existing
rebuild and build-stream safety behavior.

This synchronization deliberately does not add new hardening for two residual
upstream logging risks:

- Docker mount/path metadata can remain visible in debug command logs.
- Raw Docker container-start failure diagnostics can remain visible in error
  logs.

These risks must be documented in the synchronization report for a later task.
L3 does not authorize deletion or regression of the local rebuild protections;
it only keeps additional log hardening outside this synchronization's scope.

## Grok Decision: G1

Accept the official Grok provider implementation as-is.

The locked upstream provider attempts to run `grok` inside Docker mode, but
neither the upstream Dockerfile changes nor the local shared image currently
install Grok. This synchronization will not invent a Grok package/version
resolver or extend the Docker image.

Expected scope:

- host-mode Grok behavior comes from upstream;
- Grok Docker support remains an explicitly documented gap;
- no local Docker rejection behavior is added;
- a later task may investigate official installation and versioning evidence.

## Dependency and Packaging Policy

The fork has no local-only `pyproject.toml` or `uv.lock` changes after the
merge-base. Accept the locked upstream versions of both files, including the
`0.20.1` package metadata and Slack optional dependencies.

Use an isolated dependency environment in the execution worktree. Do not install
or reinstall the live Ductor service as part of synchronization.

## Verification Design

### Pre-merge baseline

Before the merge:

1. Confirm the worktree branch and locked commit ancestry.
2. Prepare or verify an isolated development environment.
3. Run focused Docker, rebuild, environment, and configuration tests.
4. Run Ruff, mypy, and the full pytest suite to establish the execution-session
   baseline.
5. Add and pass any missing local characterization tests.

The planning worktree's focused baseline was 157 passing Docker/rebuild/env
tests. A planning-time full pytest attempt was interrupted after it stopped
making visible progress and therefore is neither a pass nor a failure baseline.
The execution session must run and classify the full suite itself.

### Post-merge focused verification

After merging and after each compatibility fix, run focused tests for:

- Docker environment injection and log redaction;
- provider version resolution and generated build arguments;
- candidate verification and mutation ordering;
- immutable promotion, shared-container updates, and recovery;
- Docker extras and generated Dockerfile layer ordering;
- CLI rebuild failure behavior;
- configuration deep-merge and old persistent-data fixtures;
- upstream provider, task ID, Slack, Grok, workspace, and session changes touched
  by conflict resolution.

Compatibility fixes must use test-driven development: add a failing regression
test, make the minimal production change, and rerun the focused set.

### Final verification

Run, in order:

1. all relevant focused tests;
2. Ruff formatting check and lint;
3. mypy;
4. the complete pytest suite.

Use verification-before-completion. Classify every failure as:

- present in the pre-merge baseline;
- introduced by the synchronization;
- caused by the execution environment.

Synchronization regressions must be fixed. Existing or environmental failures
must be reported with evidence and must not be described as passing.

## Runtime and Safety Boundaries

The execution session must not:

- run `ductor docker rebuild` without separate explicit user approval;
- stop, remove, recreate, or update containers;
- inspect or disclose credentials, environment values, complete process
  arguments, prompts, service logs, Docker mounts, or raw subprocess
  diagnostics;
- install or restart the live Ductor service;
- mutate the user's real Ductor configuration or persistent runtime data;
- clean, reset, delete, or reuse the old
  `/home/zqxu/ductor/.worktrees/docker-image-refresh` worktree;
- use `git clean` or `git reset --hard`;
- merge the synchronization branch into `main`;
- push or create a pull request.

## Stop Conditions

Stop and request user direction when:

- the local branch no longer descends from the locked local commit;
- the locked upstream object is missing or differs from the recorded object;
- ordinary merge cannot safely represent both required behavior sets;
- a protected local capability conflicts irreconcilably with an upstream
  interface;
- a required behavior cannot be verified without a real Docker rebuild;
- verification reveals a synchronization regression that cannot be resolved
  through the approved test-driven compatibility scope;
- completing the work would require rebase, squash, cherry-picking existing
  local commits, container mutation, push, or integration into `main`.

## Deliverable of the Execution Session

The execution session will leave a verified synchronization branch in the
existing worktree and report:

- the locked local, merge-base, and upstream commits;
- the merge commit and any compatibility-fix commits;
- how each protected local capability was preserved;
- conflict and semantic-resolution decisions;
- focused, Ruff, mypy, and full pytest results;
- any existing/environmental failures;
- the L3 logging risks and G1 Grok Docker limitation;
- confirmation that no real Docker rebuild, `main` integration, push, or pull
  request occurred.

It will then stop and wait for user approval of any later integration or
operational validation.
