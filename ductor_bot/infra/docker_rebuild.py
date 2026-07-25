from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from ductor_bot.config import DockerConfig
from ductor_bot.infra.docker import DockerManager
from ductor_bot.infra.docker_image import (
    ProviderCliVersions,
    candidate_image_ref,
    inspect_image_id,
    list_direct_image_containers,
    remove_containers,
    remove_image_tag,
    resolve_provider_cli_versions,
    tag_image,
    verify_container_codex_version,
    verify_image_codex_version,
    wait_for_container_images,
)
from ductor_bot.multiagent.registry import AgentRegistry
from ductor_bot.workspace.paths import DuctorPaths


@dataclass(frozen=True, slots=True)
class CandidateImage:
    ref: str
    image_id: str
    versions: ProviderCliVersions


@dataclass(frozen=True, slots=True)
class RebuildOutcome:
    old_image_id: str | None
    candidate_ref: str
    candidate_image_id: str
    codex_version: str


def configured_container_names(
    paths: DuctorPaths,
    main_docker: DockerConfig,
) -> tuple[str, ...]:
    names = [main_docker.container_name]
    registry = AgentRegistry(paths.ductor_home / "agents.json")
    for sub in registry.load():
        docker = sub.docker or main_docker
        if (
            docker.enabled
            and docker.image_name == main_docker.image_name
            and docker.container_name not in names
        ):
            names.append(docker.container_name)
    return tuple(names)


async def _prepare_candidate(
    manager: DockerManager,
    candidate_ref: str,
    versions: ProviderCliVersions,
) -> str:
    if not await manager._build_image(candidate_ref, versions):
        raise RuntimeError("Docker candidate build failed")
    image_id = inspect_image_id(candidate_ref)
    if image_id is None:
        raise RuntimeError("Docker candidate image cannot be inspected")
    verify_image_codex_version(candidate_ref, versions.codex)
    return image_id


async def build_verified_candidate(
    config: DockerConfig,
    paths: DuctorPaths,
) -> CandidateImage:
    versions = resolve_provider_cli_versions()
    candidate_ref = candidate_image_ref(config.image_name)
    manager = DockerManager(config, paths)
    try:
        image_id = await _prepare_candidate(manager, candidate_ref, versions)
    except Exception:
        with suppress(RuntimeError):
            remove_image_tag(candidate_ref)
        raise
    return CandidateImage(candidate_ref, image_id, versions)


async def rebuild_docker_image(
    config: DockerConfig,
    paths: DuctorPaths,
    *,
    runtime_was_running: bool,
    stop_runtime: Callable[[], None],
    start_runtime: Callable[[], None],
) -> RebuildOutcome:
    candidate = await build_verified_candidate(config, paths)
    old_id = inspect_image_id(config.image_name)
    names = configured_container_names(paths, config)
    stopped = False
    promoted = False
    start_attempted = False
    try:
        stop_runtime()
        stopped = True
        tag_image(candidate.image_id, config.image_name)
        promoted = True
        if old_id is not None:
            remove_containers(list_direct_image_containers(old_id))
        if runtime_was_running:
            start_attempted = True
            start_runtime()
            wait_for_container_images(names, candidate.image_id)
            verify_container_codex_version(names[0], candidate.versions.codex)
    except Exception:
        if start_attempted:
            with suppress(Exception):
                stop_runtime()
        if promoted and old_id is not None:
            with suppress(Exception):
                remove_containers(list_direct_image_containers(candidate.image_id))
                tag_image(old_id, config.image_name)
        if stopped and runtime_was_running and (not promoted or old_id is not None):
            with suppress(Exception):
                start_runtime()
        raise
    return RebuildOutcome(
        old_image_id=old_id,
        candidate_ref=candidate.ref,
        candidate_image_id=candidate.image_id,
        codex_version=candidate.versions.codex,
    )
