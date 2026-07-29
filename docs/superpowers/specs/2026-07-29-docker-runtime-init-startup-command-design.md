# Docker Runtime Init and Startup Command Design

## Context

The main Ductor sandbox used to start workspace daemons through a custom image
`CMD`. Rebuilding `ductor-sandbox` from the framework `Dockerfile.sandbox`
restored the default `CMD ["sleep", "infinity"]`. The daemon scripts remained
on the host-mounted workspace, but the container no longer invoked
`workspace/daemons/start.sh`.

The default container also runs `sleep infinity` directly as PID 1. It does not
act as a process subreaper, so orphaned descendants can remain as zombies.
Encoding either daemon startup or PID-1 behavior in a derived image makes the
behavior vulnerable to later image rebuilds and prevents the derived image from
automatically receiving base-image software upgrades.

## Goals

- Keep main and sub-agents on the standard, upgradeable `ductor-sandbox` image.
- Give every Ductor-managed sandbox a real minimal init process that reaps
  orphaned children.
- Let the main sandbox override the image command through persistent Ductor
  configuration and invoke the existing `workspace/daemons/start.sh`.
- Leave sub-agent sandboxes on the image's default `sleep infinity` command.
- Preserve behavior across `ductor docker rebuild` without rebuilding a custom
  image.

## Non-goals

- Moving daemon implementations into the Ductor Python package.
- Replacing `workspace/daemons/start.sh`.
- Adding a general-purpose lifecycle hook framework.
- Changing daemon scheduling, mail handling, digest generation, or notification
  behavior.
- Automatically adding daemon startup commands to every installation.

## Considered Approaches

### 1. Runtime init plus configurable container command (selected)

Add Docker's `--init` flag to every sandbox container and add an optional
`docker.command` argument list. Ductor appends configured command arguments
after the image name in `docker run`.

This keeps software packaging in the standard image while making process
supervision and main-only daemon startup runtime concerns. Image rebuilds
continue to update all packaged software.

### 2. Main-only derived image

Build `ductor-main-sandbox FROM ductor-sandbox` with a custom `CMD`.

This is rejected because the derived image is pinned to the base image state at
build time and must be rebuilt after every base upgrade. The existing Ductor
image rebuild path can also overwrite the derived tag with the standard
Dockerfile output.

### 3. Separate host systemd or sidecar daemon service

Run the workspace daemons independently of the main sandbox.

This is rejected for this change because it duplicates container lifecycle,
mount, secret-injection, and inter-agent networking configuration. It creates a
second deployment surface for processes that already belong to the main
sandbox.

## Configuration Interface

`DockerConfig` gains one field:

```python
command: list[str] = Field(default_factory=list)
```

An empty list preserves the image's default command. A non-empty list is passed
as exact Docker command arguments; Ductor performs no shell parsing.

The main installation will use:

```json
{
  "docker": {
    "image_name": "ductor-sandbox",
    "container_name": "ductor-sandbox",
    "command": [
      "/bin/bash",
      "-lc",
      "bash /ductor/workspace/daemons/start.sh && exec sleep infinity"
    ]
  }
}
```

Sub-agent Docker configurations omit `command` and therefore retain the image
default.

## Container Lifecycle

`DockerManager._start_container()` will construct the relevant command shape as:

```text
docker run -d --init ... <image> [configured command arguments...]
```

Docker's init process becomes container PID 1. For an unconfigured sub-agent it
launches the image's default `sleep infinity` as its child. For main it launches
the configured shell, which runs `start.sh` and then replaces itself with
`sleep infinity`.

`start.sh` starts the mail daemon, digest daemon, notification broker, and
engine in the background. When the launcher exits, those processes are adopted
by Docker's init process, which reaps them if they terminate. The main container
therefore does not require the custom workspace `init.py` as PID 1.

## Upgrade Behavior

`ductor docker rebuild` continues to build and promote the standard
`ductor-sandbox` image. Container recreation reads `docker.command` from
persistent configuration and reapplies `--init`, so daemon startup and zombie
reaping do not depend on image metadata.

The Ductor application change must be committed to the maintained fork. A
future application upgrade must merge this commit or contain an equivalent
upstream feature. Image upgrades alone cannot overwrite it.

## Error Handling

- An empty `docker.command` is valid and uses the image default.
- Docker receives command items as separate arguments, avoiding accidental
  re-tokenization.
- A command that exits causes the container to stop. The existing
  `ensure_running()` path detects the stopped container on the next use and
  attempts recovery; Docker output remains available for diagnosis.
- Existing command-log redaction remains responsible for protecting
  environment secrets. The configured main command contains no secrets.

## Testing

Unit tests will prove:

- `DockerConfig.command` defaults to an independent empty list.
- Explicit command arguments survive Pydantic parsing.
- Every generated `docker run` includes `--init` before the image.
- Empty configuration adds nothing after the image.
- A configured command is appended after the image with argument boundaries
  preserved.

Operational verification after deployment will prove:

- Main and sub-agent containers use `ductor-sandbox`.
- `HostConfig.Init` is true for all managed containers.
- Main has one live instance of each expected daemon.
- Sub-agent containers do not start main daemons.
- The mail heartbeat advances after restart.
- Rebuilding or recreating the standard image reapplies the runtime behavior.
