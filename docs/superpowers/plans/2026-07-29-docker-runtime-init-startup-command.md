# Docker Runtime Init and Startup Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every Ductor sandbox on the standard upgradeable image while
using Docker's init process for zombie reaping and a main-only configured
command to start the existing workspace daemons.

**Architecture:** `DockerManager` will always pass `--init` to `docker run`.
`DockerConfig` will expose an optional argument-vector `command`; when non-empty,
`DockerManager` appends it after the image name without shell tokenization. The
main runtime config will invoke the mounted `workspace/daemons/start.sh`, while
sub-agent configurations remain empty and use the image's default command.

**Tech Stack:** Python 3.11+, Pydantic 2, asyncio subprocess execution, Docker
CLI, pytest, Ruff, mypy, JSON runtime configuration.

## Global Constraints

- The approved design is
  `docs/superpowers/specs/2026-07-29-docker-runtime-init-startup-command-design.md`.
- Execute in a new isolated worktree created from `main` at or after the plan
  commit. Use branch `feat/docker-runtime-init-startup-command` and directory
  `.worktrees/docker-runtime-init-startup-command`.
- Do not use a derived Docker image and do not modify `Dockerfile.sandbox`.
- Keep main and sub-agents on `ductor-sandbox`.
- Keep daemon implementations and `workspace/daemons/start.sh` unchanged.
- Add `--init` to every Ductor-managed sandbox container.
- `docker.command` is an exact `list[str]`; do not parse, split, or interpolate
  its items.
- An empty `docker.command` must preserve the image default command.
- Only the main config receives a non-empty command. Do not add it to
  `agents.json` or sub-agent configs.
- Follow strict TDD for every code behavior: observe RED, write the minimum
  implementation, then observe GREEN.
- Commit each code task independently.
- Do not rebuild `ductor-sandbox`; this feature changes container runtime
  arguments, not image contents.
- Do not print `.env`, secret values, complete redacted-away Docker environment
  flags, or historical service logs.
- Back up runtime config before deployment and keep the rollback commands ready.

## File Structure

- Modify `ductor_bot/config.py`: add the persistent optional Docker command
  argument vector.
- Modify `ductor_bot/infra/docker.py`: add Docker `--init` and append configured
  command arguments after the image.
- Modify `tests/test_config.py`: prove command default isolation and exact
  Pydantic parsing.
- Modify `tests/infra/test_docker.py`: prove Docker init and command ordering.
- Modify `/home/zqxu/.ductor/config/config.json` only during deployment: add the
  main-only command.

---

### Task 0: Create an Isolated Worktree and Verify the Focused Baseline

**Files:**

- Read: `docs/superpowers/specs/2026-07-29-docker-runtime-init-startup-command-design.md`
- Read: `docs/superpowers/plans/2026-07-29-docker-runtime-init-startup-command.md`
- Create worktree:
  `/home/zqxu/ductor/.worktrees/docker-runtime-init-startup-command`

**Interfaces:**

- Consumes: `main` containing the approved spec and this plan.
- Produces: clean branch `feat/docker-runtime-init-startup-command`.

- [ ] **Step 1: Confirm the source checkout and create the worktree**

Run from `/home/zqxu/ductor`:

```bash
git status --short
git worktree add \
  /home/zqxu/ductor/.worktrees/docker-runtime-init-startup-command \
  -b feat/docker-runtime-init-startup-command
```

Expected: the only pre-existing status entry may be the ignored-compatible
`?? worktrees` symlink; the new worktree is created from current `main`.

- [ ] **Step 2: Confirm isolation and read the approved documents**

Run:

```bash
cd /home/zqxu/ductor/.worktrees/docker-runtime-init-startup-command
git branch --show-current
git status --short
sed -n '1,240p' \
  docs/superpowers/specs/2026-07-29-docker-runtime-init-startup-command-design.md
sed -n '1,320p' \
  docs/superpowers/plans/2026-07-29-docker-runtime-init-startup-command.md
```

Expected: branch is `feat/docker-runtime-init-startup-command` and status is
clean.

- [ ] **Step 3: Run the focused baseline**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/test_config.py \
  tests/infra/test_docker.py \
  -q
```

Expected: all focused tests pass before feature changes. If they do not, stop
and report the exact pre-existing failures before editing code.

---

### Task 1: Add the Exact Docker Command Configuration Contract

**Files:**

- Modify: `ductor_bot/config.py:39-50`
- Modify: `tests/test_config.py:182-186`

**Interfaces:**

- Consumes: existing `DockerConfig(BaseModel)`.
- Produces:
  `DockerConfig.command: list[str] = Field(default_factory=list)`.

- [ ] **Step 1: Write failing command configuration tests**

Add these tests immediately after `test_docker_config_fields()` in
`tests/test_config.py`:

```python
def test_docker_config_command_defaults_to_independent_empty_lists() -> None:
    first = DockerConfig()
    second = DockerConfig()

    first.command.append("changed")

    assert first.command == ["changed"]
    assert second.command == []


def test_docker_config_preserves_command_argument_boundaries() -> None:
    command = [
        "/bin/bash",
        "-lc",
        "bash /ductor/workspace/daemons/start.sh && exec sleep infinity",
    ]

    config = DockerConfig(command=command)

    assert config.command == command
```

- [ ] **Step 2: Run the two tests and observe RED**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/test_config.py::test_docker_config_command_defaults_to_independent_empty_lists \
  tests/test_config.py::test_docker_config_preserves_command_argument_boundaries \
  -q
```

Expected: both tests fail with `AttributeError` because `DockerConfig` does not
yet expose `command`.

- [ ] **Step 3: Add the minimal Pydantic field**

In `DockerConfig`, insert the field after `container_name`:

```python
class DockerConfig(BaseModel):
    """Settings for Docker-based CLI sandboxing."""

    enabled: bool = False
    image_name: str = "ductor-sandbox"
    container_name: str = "ductor-sandbox"
    command: list[str] = Field(default_factory=list)
    auto_build: bool = True
    mount_host_cache: bool = False
    mounts: list[str] = Field(default_factory=list)
    published_ports: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Verify GREEN and static quality**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/test_config.py::test_docker_config_command_defaults_to_independent_empty_lists \
  tests/test_config.py::test_docker_config_preserves_command_argument_boundaries \
  -q
/home/zqxu/ductor/.venv/bin/ruff check \
  ductor_bot/config.py tests/test_config.py
```

Expected: two tests pass and Ruff exits 0.

- [ ] **Step 5: Commit the configuration contract**

```bash
git add ductor_bot/config.py tests/test_config.py
git commit -m "feat(docker): configure container command arguments"
```

---

### Task 2: Run Every Sandbox Under Docker Init

**Files:**

- Modify: `ductor_bot/infra/docker.py:350-370`
- Modify: `tests/infra/test_docker.py` inside `TestDockerManager`

**Interfaces:**

- Consumes:
  `DockerManager._start_container(name: str, image: str) -> bool`.
- Produces: every generated `docker run` beginning with
  `docker run -d --init --name ...`.

- [ ] **Step 1: Write the failing Docker init test**

Add this test inside `TestDockerManager` in `tests/infra/test_docker.py`:

```python
    async def test_start_container_enables_docker_init(
        self,
        docker_config: DockerConfig,
        docker_paths: DuctorPaths,
    ) -> None:
        from ductor_bot.infra.docker import DockerManager

        manager = DockerManager(docker_config, docker_paths)
        run_args: tuple[str, ...] = ()

        async def capture(*args: str, **_kwargs: object) -> tuple[int, str]:
            nonlocal run_args
            run_args = args
            return 0, "container-id"

        with (
            patch.object(manager, "_exec", side_effect=capture),
            patch("ductor_bot.infra.docker._needs_uid_mapping", return_value=False),
        ):
            started = await manager._start_container("test-ctr", "test-img")

        assert started is True
        assert run_args[:5] == ("docker", "run", "-d", "--init", "--name")
        assert run_args[-1] == "test-img"
```

- [ ] **Step 2: Run the test and observe RED**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/infra/test_docker.py::TestDockerManager::test_start_container_enables_docker_init \
  -q
```

Expected: the prefix assertion fails because the fourth argument is currently
`--name`, not `--init`.

- [ ] **Step 3: Add the minimal Docker runtime flag**

Change the start of the `cmd` list in
`DockerManager._start_container()` to:

```python
        cmd: list[str] = [
            "docker",
            "run",
            "-d",
            "--init",
            "--name",
            name,
            "-w",
            _CONTAINER_WS,
```

Do not add `--init` to the Dockerfile or make it conditional.

- [ ] **Step 4: Verify GREEN and the Docker manager regression set**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/infra/test_docker.py::TestDockerManager::test_start_container_enables_docker_init \
  -q
/home/zqxu/ductor/.venv/bin/pytest tests/infra/test_docker.py -q
/home/zqxu/ductor/.venv/bin/ruff check \
  ductor_bot/infra/docker.py tests/infra/test_docker.py
```

Expected: the new test and the full Docker manager test module pass; Ruff exits
0.

- [ ] **Step 5: Commit Docker init support**

```bash
git add ductor_bot/infra/docker.py tests/infra/test_docker.py
git commit -m "fix(docker): run sandbox containers with init"
```

---

### Task 3: Append Configured Commands After the Image

**Files:**

- Modify: `ductor_bot/infra/docker.py:410-425`
- Modify: `tests/infra/test_docker.py` inside `TestDockerManager`

**Interfaces:**

- Consumes: `DockerConfig.command: list[str]`.
- Produces: exact Docker CLI ordering
  `docker run [options] <image> <command[0]> ... <command[n]>`.

- [ ] **Step 1: Write the failing command-order test**

Add this test inside `TestDockerManager`:

```python
    async def test_start_container_appends_configured_command_after_image(
        self,
        docker_paths: DuctorPaths,
    ) -> None:
        from ductor_bot.infra.docker import DockerManager

        command = [
            "/bin/bash",
            "-lc",
            "bash /ductor/workspace/daemons/start.sh && exec sleep infinity",
        ]
        config = DockerConfig(
            enabled=True,
            image_name="test-img",
            container_name="test-ctr",
            command=command,
        )
        manager = DockerManager(config, docker_paths)
        run_args: tuple[str, ...] = ()

        async def capture(*args: str, **_kwargs: object) -> tuple[int, str]:
            nonlocal run_args
            run_args = args
            return 0, "container-id"

        with (
            patch.object(manager, "_exec", side_effect=capture),
            patch("ductor_bot.infra.docker._needs_uid_mapping", return_value=False),
        ):
            started = await manager._start_container("test-ctr", "test-img")

        assert started is True
        image_index = run_args.index("test-img")
        assert list(run_args[image_index + 1 :]) == command
```

- [ ] **Step 2: Run the test and observe RED**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/infra/test_docker.py::TestDockerManager::test_start_container_appends_configured_command_after_image \
  -q
```

Expected: the final assertion fails because there are currently no arguments
after `test-img`.

- [ ] **Step 3: Append the exact configured argument vector**

Replace:

```python
        cmd.append(image)
```

with:

```python
        cmd += [image, *self._config.command]
```

Do not join the command into a string and do not invoke `shlex`.

- [ ] **Step 4: Verify GREEN and combined focused behavior**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/infra/test_docker.py::TestDockerManager::test_start_container_enables_docker_init \
  tests/infra/test_docker.py::TestDockerManager::test_start_container_appends_configured_command_after_image \
  -q
/home/zqxu/ductor/.venv/bin/pytest \
  tests/test_config.py tests/infra/test_docker.py \
  -q
/home/zqxu/ductor/.venv/bin/ruff check \
  ductor_bot/config.py ductor_bot/infra/docker.py \
  tests/test_config.py tests/infra/test_docker.py
```

Expected: both new runtime tests and both focused modules pass; Ruff exits 0.

- [ ] **Step 5: Commit command application**

```bash
git add ductor_bot/infra/docker.py tests/infra/test_docker.py
git commit -m "feat(docker): apply configured container command"
```

---

### Task 4: Complete Code Verification

**Files:**

- Verify: all tracked files changed by Tasks 1-3.
- Do not modify unrelated failures.

**Interfaces:**

- Consumes: three feature commits.
- Produces: evidence that focused tests, formatting, lint, typing, and the full
  suite have been evaluated before deployment.

- [ ] **Step 1: Verify the branch diff and formatting**

Run:

```bash
git status --short
git diff main...HEAD --check
/home/zqxu/ductor/.venv/bin/ruff format --check \
  ductor_bot/config.py ductor_bot/infra/docker.py \
  tests/test_config.py tests/infra/test_docker.py
```

Expected: worktree is clean, diff check exits 0, and formatting is clean.

- [ ] **Step 2: Run focused tests and lint**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/test_config.py tests/infra/test_docker.py \
  -q
/home/zqxu/ductor/.venv/bin/ruff check \
  ductor_bot/config.py ductor_bot/infra/docker.py \
  tests/test_config.py tests/infra/test_docker.py
```

Expected: all focused tests pass and Ruff exits 0.

- [ ] **Step 3: Run strict typing**

Run:

```bash
/home/zqxu/ductor/.venv/bin/mypy ductor_bot
```

Expected: mypy exits 0.

- [ ] **Step 4: Run the full test suite**

Run:

```bash
/home/zqxu/ductor/.venv/bin/pytest -q
```

Expected: report the exact pass/fail totals. If failures exist, compare them
with a fresh run on `main` or demonstrate that they are unrelated before
proceeding. Do not claim the full suite passes unless exit status is 0.

---

### Task 5: Deploy Main-Only Startup and Verify Runtime State

**Files:**

- Back up:
  `/home/zqxu/.ductor/config/config.json`
- Modify:
  `/home/zqxu/.ductor/config/config.json`
- Install from:
  `/home/zqxu/ductor/.worktrees/docker-runtime-init-startup-command`

**Interfaces:**

- Consumes:
  - verified feature branch
  - `docker.command`
  - existing `/home/zqxu/.ductor/workspace/daemons/start.sh`
- Produces:
  - all three containers with `HostConfig.Init=true`
  - main-only daemon startup
  - standard `ductor-sandbox` image for every container

- [ ] **Step 1: Record pre-deployment state and create an explicit backup**

Run:

```bash
ductor service status
docker inspect ductor-sandbox ductor-sub-serveradmin ductor-sub-botbuilder \
  --format '{{.Name}} image={{.Config.Image}} init={{.HostConfig.Init}} args={{json .Args}}'
mkdir -p /home/zqxu/.ductor/backups/docker-runtime-init-20260729
cp /home/zqxu/.ductor/config/config.json \
  /home/zqxu/.ductor/backups/docker-runtime-init-20260729/config.json
```

Expected: the service is running, existing containers report `init=<nil>` or
`init=false`, and the backup file exists.

- [ ] **Step 2: Install the verified branch**

From the feature worktree, run:

```bash
uv tool install --force --from \
  /home/zqxu/ductor/.worktrees/docker-runtime-init-startup-command \
  ductor
ductor --version
```

Expected: installation succeeds and `ductor --version` reports the project
version from the verified branch.

- [ ] **Step 3: Add only the main command to runtime configuration**

Use `apply_patch` to make this exact change:

```diff
*** Begin Patch
*** Update File: /home/zqxu/.ductor/config/config.json
@@
     "image_name": "ductor-sandbox",
     "container_name": "ductor-sandbox",
+    "command": [
+      "/bin/bash",
+      "-lc",
+      "bash /ductor/workspace/daemons/start.sh && exec sleep infinity"
+    ],
     "auto_build": true,
*** End Patch
```

Do not change `agents.json`, sub-agent configs, extras, mounts, tokens, or other
runtime settings.

- [ ] **Step 4: Restart once and confirm service recovery**

Run:

```bash
ductor restart
ductor service status
```

Expected: restart exits successfully and `ductor.service` is active.

- [ ] **Step 5: Verify images, init, and command separation**

Run:

```bash
docker inspect ductor-sandbox ductor-sub-serveradmin ductor-sub-botbuilder \
  --format '{{.Name}} image={{.Config.Image}} init={{.HostConfig.Init}} args={{json .Args}}'
```

Expected:

- all three report `image=ductor-sandbox`;
- all three report `init=true`;
- main args contain `/ductor/workspace/daemons/start.sh`;
- sub-agent args remain `["sleep","infinity"]`.

- [ ] **Step 6: Verify main-only daemon processes and absence of zombies**

Run:

```bash
docker top ductor-sandbox -eo pid,ppid,state,args
docker top ductor-sub-serveradmin -eo pid,ppid,state,args
docker top ductor-sub-botbuilder -eo pid,ppid,state,args
```

Expected:

- main contains exactly one live `mail_daemon.py`;
- main contains exactly one live `generate_digest.py`;
- main contains exactly one live `notification_broker.py`;
- main contains exactly one live `/ductor/engine/engine.py`;
- no process state begins with `Z`;
- neither sub-agent contains any of the four main daemon commands.

- [ ] **Step 7: Verify daemon heartbeat and launcher logs without exposing secrets**

Run:

```bash
stat -c '%y %n' \
  /home/zqxu/.ductor/workspace/skills/personal-assistant/.mail_daemon.heartbeat
docker logs --tail 80 ductor-sandbox 2>&1 \
  | sed -E 's/(PASSWORD|TOKEN|SECRET|API_KEY)=[^ ]+/\1=***/g'
```

Expected: heartbeat time is later than the restart and launcher output reports
the expected daemon PIDs. Do not print environment variables or unredacted
service command lines.

- [ ] **Step 8: Use the explicit rollback only if deployment verification fails**

If any required runtime check fails, run:

```bash
cp /home/zqxu/.ductor/backups/docker-runtime-init-20260729/config.json \
  /home/zqxu/.ductor/config/config.json
uv tool install --force --from /home/zqxu/ductor ductor
ductor restart
ductor service status
```

Then report the failed check and the restored state. Do not layer additional
fixes onto a failed deployment.

- [ ] **Step 9: Report branch integration state**

Run:

```bash
git status --short
git log --oneline main..HEAD
```

Expected: worktree is clean and the three feature commits are listed. Report
that runtime is installed from the feature branch and ask before merging the
branch into `main`.

## Completion Checklist

- [ ] Each new behavior was observed RED before production code changed.
- [ ] Each task was observed GREEN before its commit.
- [ ] `DockerConfig.command` preserves exact argument boundaries.
- [ ] Every generated sandbox `docker run` contains `--init`.
- [ ] Empty command configuration preserves image defaults.
- [ ] Main alone invokes `workspace/daemons/start.sh`.
- [ ] All containers remain on `ductor-sandbox`.
- [ ] Focused tests, Ruff, and mypy pass.
- [ ] Full pytest status is reported exactly.
- [ ] Runtime has `init=true`, no zombie state, and the expected main daemons.
- [ ] Runtime config backup and rollback path remain available.
