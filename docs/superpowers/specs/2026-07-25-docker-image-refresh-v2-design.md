# Docker Image Refresh v2 Design

Date: 2026-07-25

Branch: `feat/docker-image-refresh-v2`

Baseline: `08ecc315bd20defaf886cf5d2232d52e89099224`

## Objective

Make `ductor docker rebuild` reliably build and deploy a shared `ductor-sandbox`
image containing the provider CLI versions resolved from npm at rebuild time.
The first priority is a verified Codex upgrade that allows a new session to use
`gpt-5.6-sol`. Development, Office, PDF, and OCR tooling follows as a separate
second phase.

The design must preserve normal Docker/BuildKit caching and every configured
`docker.extras` entry, including the Playwright Python package. It must not install
Chromium, run `playwright install`, add browser profiles, or add browser mounts.

## Root Cause

The previous formal rebuild path did not have a candidate image stage. It:

1. resolved provider versions;
2. stopped the Ductor runtime and removed containers using the old image;
3. built directly into the configured production tag;
4. smoke-checked that mutable production tag;
5. attempted to restart and verify the runtime.

The independently built diagnostic image was never promoted by the formal
workflow. Its successful Codex version therefore did not prove that the formal
rebuild deployed that image. The version chain broke before a candidate immutable
image ID was captured and verified.

The v2 implementation will start from the baseline and will not cherry-pick the
previous Docker commits.

## Chosen Approach: Candidate-First Promotion

The rebuild is divided into two parts: a non-disruptive candidate build and a
short deployment cutover.

### Candidate build

1. Resolve the latest concrete versions with these npm queries:
   - `@anthropic-ai/claude-code`
   - `@openai/codex`
   - `@google/gemini-cli`
2. Validate all three responses as concrete semantic versions.
3. Generate a unique candidate tag in the same repository as the configured
   image, for example `ductor-sandbox:ductor-candidate-<random>`.
4. Generate the Dockerfile from the resolved base Dockerfile plus every selected
   `docker.extras` entry.
5. Build only the candidate tag, passing the three concrete versions as build
   arguments. Use normal BuildKit cache behavior; never use global `--no-cache`.
6. Inspect the candidate tag and record its canonical immutable image ID.
7. Run `codex --version` directly from the candidate image and require an exact
   match with the Codex version resolved in step 1.

No service, production tag, or existing container is changed before all candidate
steps succeed.

### Promotion and deployment

1. Record the current production image ID, if it exists.
2. Stop the Ductor runtime only after candidate verification.
3. Tag the verified candidate immutable ID as the configured production image.
4. Remove only containers that directly use the old shared image ID.
5. Restart the runtime so the main agent and enabled sub-agents recreate their
   containers from the promoted image.
6. Verify that `ductor-sandbox`, `ductor-sub-serveradmin`, and
   `ductor-sub-botbuilder` are running and use the candidate immutable image ID.
7. Check Codex in one running container and require the same resolved version.
8. Retain the candidate tag through post-rebuild acceptance so the candidate can
   be run directly again. It may be removed only after the user accepts the
   deployment; the production tag keeps the image reachable afterward.

The command succeeds only after deployment verification succeeds.

## Failure Handling

Failures are divided by the mutation boundary.

Before promotion:

- return a nonzero status;
- leave the production tag and all running containers untouched;
- remove the candidate tag on a best-effort basis;
- report only the failed stage, safe package/version values, safe image IDs, and
  exit status.

During or after promotion:

- return a nonzero status;
- if an old immutable image ID exists, make one bounded best-effort attempt to
  restore its production tag and restart the old runtime;
- do not recreate the previous multi-state rollback framework.

Errors and logs must not contain credentials, environment variables, prompts,
complete subprocess arguments, or captured subprocess stdout/stderr. External
command output is parsed internally and reduced to safe structured values.

## Dockerfile and Cache Layout

The generated image layers will be ordered as follows:

1. base operating system and core runtime;
2. phase-two development, Office, PDF, and OCR tools;
3. configured `docker.extras`;
4. one provider CLI layer containing Claude, Codex, and Gemini;
5. final user, working directory, labels, and command metadata.

The extras generator must insert existing extras before the provider marker
instead of appending them after the provider layer. Changing a provider version
then invalidates only the provider layer and following metadata. The large tool
and extras layers remain cacheable.

The three providers stay in one npm layer. Updating one provider reruns that
single layer, but the npm cache mount avoids unnecessary package downloads.
Splitting providers into three layers would add complexity without a meaningful
operational benefit.

Changing the base image, tools, or selected extras naturally invalidates the
affected layer and later layers.

## Shared Image Scope

The configured image is shared by the main agent and all enabled Docker
sub-agents that reference the same image name. Deployment will derive the target
container names from validated Ductor configuration without printing unrelated
configuration data.

Container verification uses exact immutable image IDs, not tag strings.
Unrelated containers and images are not removed.

## Phase One: Provider CLI Reliability

Phase one contains only work needed for reliable provider build and deployment:

- concrete npm version resolution;
- provider build arguments and Dockerfile layer;
- insertion of existing extras before the provider layer;
- unique candidate build;
- candidate Codex verification;
- candidate promotion;
- shared-container recreation and immutable-ID verification;
- nonzero failure status and sanitized diagnostics.

No new development, Office, PDF, OCR, or browser tooling is added in this phase.
Existing configured extras remain present but do not gain a new smoke-check
matrix.

After phase-one code and quality checks pass, reinstall the local fork and start a
phase-one formal rebuild in a background terminal. Immediately notify the user
and stop. Do not poll or read the complete build log. Continue only after the
user reports that the terminal has finished.

Phase two starts only after the phase-one candidate, shared containers, and a new
`gpt-5.6-sol` Codex session have been accepted.

## Phase Two: Development and Document Tools

Phase two adds the requested cached base layers:

- common command-line development tools;
- LibreOffice Writer, Calc, and Impress;
- PDF inspection and manipulation tools;
- OCR tooling and required English, Simplified Chinese, and Traditional Chinese
  language data;
- Python packages for DOCX, XLSX, PPTX, and PDF processing.

All configured `docker.extras` remain generated after these base tools and before
the provider layer. The Playwright extra installs only the Python package.

Phase two must explicitly avoid:

- Chromium or another browser binary;
- `playwright install`;
- `/ms-playwright`;
- browser cache/profile initialization;
- browser profile or cache mounts.

After phase-two code and quality checks pass, reinstall the local fork and launch
the final formal rebuild in a background terminal. Again, immediately notify the
user and wait for the user's completion report before inspecting results.

## TDD Strategy

Implementation begins with a test that reproduces the actual break:

- when candidate verification fails, `ductor docker rebuild` must not stop the
  runtime, retag the production image, or remove any existing container.

This test is RED on the baseline because the baseline rebuild stops the service
and removes the current container/image before any new image is verified.

Additional focused tests will cover:

- exact npm query-to-build-argument propagation for all three providers;
- candidate tag uniqueness and canonical image ID capture;
- exact candidate Codex version comparison;
- promotion only after successful candidate verification;
- all three expected containers using the same candidate image ID;
- nonzero command status for build, verification, promotion, or deployment
  failure;
- absence of subprocess diagnostics and secret-bearing data in errors;
- existing extras inserted before the provider layer;
- Playwright remaining a Python-only extra;
- phase-two tools present without browser installation instructions.

Tests will use small command-runner boundaries and event-order assertions. They
will not introduce a general workflow engine or an extensive hard-check matrix.

Each independent task receives its own commit. At minimum:

1. provider version resolution and Dockerfile contract;
2. candidate build and pre-promotion verification;
3. promotion and shared-container deployment;
4. CLI failure semantics and sanitized reporting;
5. phase-two development/document tool layers and extras preservation.

Every task follows RED, minimal implementation, and GREEN before committing.

## Verification

During development:

- focused unit tests for each RED/GREEN task;
- complete relevant unit tests;
- Ruff formatting and lint checks;
- mypy.

The final operational acceptance remains limited to:

1. Directly running the candidate image reports a Codex version exactly equal to
   the version resolved from npm for that rebuild.
2. `ductor-sandbox`, `ductor-sub-serveradmin`, and
   `ductor-sub-botbuilder` are running and use the same candidate immutable image
   ID; a container Codex spot-check matches.
3. A new Codex session successfully uses `gpt-5.6-sol`.

Phase-two tool presence is checked during its focused build verification without
expanding the final operational acceptance matrix.

## Explicit Non-Goals

This work will not:

- cherry-pick or transplant Docker commits after the baseline;
- use the old diagnostic image as the production candidate;
- implement global cache disabling;
- build a generalized transaction/workflow engine;
- add extensive rollback orchestration;
- inspect service logs, environment variables, Docker mounts, credentials, or
  complete process arguments for diagnosis;
- expose raw subprocess output in errors or reports.
