from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ductor_bot.config import DockerConfig
from ductor_bot.infra.docker_image import ProviderCliVersions
from ductor_bot.workspace.paths import DuctorPaths


@pytest.fixture
def rebuild_paths(tmp_path: Path) -> DuctorPaths:
    home = tmp_path / ".ductor"
    home.mkdir()
    framework = tmp_path / "framework"
    framework.mkdir()
    (framework / "Dockerfile.sandbox").write_text(
        "FROM node:22\n# -- Ductor configured extras insertion point --\n"
    )
    return DuctorPaths(
        ductor_home=home,
        home_defaults=framework / "workspace",
        framework_root=framework,
    )


async def test_candidate_verification_failure_has_no_runtime_or_tag_mutation(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import build_verified_candidate

    versions = ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    stop_runtime = Mock()
    tag_production = Mock()
    remove_containers = Mock()

    with (
        patch(
            "ductor_bot.infra.docker_rebuild.resolve_provider_cli_versions",
            return_value=versions,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.candidate_image_ref",
            return_value="ductor-sandbox:ductor-candidate-test",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.DockerManager._build_image",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            return_value=f"sha256:{'b' * 64}",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.verify_image_codex_version",
            side_effect=RuntimeError("candidate Codex version mismatch"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_image_tag") as cleanup,
        pytest.raises(RuntimeError, match="candidate Codex version mismatch"),
    ):
        await build_verified_candidate(
            DockerConfig(enabled=True),
            rebuild_paths,
        )

    stop_runtime.assert_not_called()
    tag_production.assert_not_called()
    remove_containers.assert_not_called()
    cleanup.assert_called_once_with("ductor-sandbox:ductor-candidate-test")


async def test_build_verified_candidate_orders_resolve_build_inspect_verify(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import build_verified_candidate

    events: list[str] = []
    image_id = f"sha256:{'b' * 64}"
    versions = ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    with (
        patch(
            "ductor_bot.infra.docker_rebuild.resolve_provider_cli_versions",
            side_effect=lambda: events.append("resolve") or versions,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.candidate_image_ref",
            return_value="ductor-sandbox:ductor-candidate-test",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.DockerManager._build_image",
            new=AsyncMock(side_effect=lambda *_: events.append("build") or True),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            side_effect=lambda *_: events.append("inspect") or image_id,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.verify_image_codex_version",
            side_effect=lambda *_: events.append("verify"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_image_tag") as cleanup,
    ):
        candidate = await build_verified_candidate(
            DockerConfig(enabled=True),
            rebuild_paths,
        )

    assert events == ["resolve", "build", "inspect", "verify"]
    assert candidate.ref == "ductor-sandbox:ductor-candidate-test"
    assert candidate.image_id == image_id
    assert candidate.versions.codex == "0.144.6"
    cleanup.assert_not_called()


def test_configured_container_names_selects_enabled_shared_image_agents(
    rebuild_paths: DuctorPaths,
) -> None:
    import json

    from ductor_bot.infra.docker_rebuild import configured_container_names

    agents = [
        {
            "name": "serveradmin",
            "docker": {
                "enabled": True,
                "image_name": "ductor-sandbox",
                "container_name": "ductor-sub-serveradmin",
            },
        },
        {
            "name": "botbuilder",
            "docker": {
                "enabled": True,
                "image_name": "ductor-sandbox",
                "container_name": "ductor-sub-botbuilder",
            },
        },
        {
            "name": "other",
            "docker": {
                "enabled": True,
                "image_name": "other-image",
                "container_name": "other-container",
            },
        },
    ]
    (rebuild_paths.ductor_home / "agents.json").write_text(json.dumps(agents))
    main_docker = DockerConfig(
        enabled=True,
        image_name="ductor-sandbox",
        container_name="ductor-sandbox",
    )

    assert configured_container_names(rebuild_paths, main_docker) == (
        "ductor-sandbox",
        "ductor-sub-serveradmin",
        "ductor-sub-botbuilder",
    )


async def test_rebuild_promotes_only_after_candidate_and_verifies_shared_containers(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import (
        CandidateImage,
        rebuild_docker_image,
    )

    old_id = f"sha256:{'a' * 64}"
    new_id = f"sha256:{'b' * 64}"
    versions = ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    candidate = CandidateImage(
        "ductor-sandbox:ductor-candidate-test",
        new_id,
        versions,
    )
    names = (
        "ductor-sandbox",
        "ductor-sub-serveradmin",
        "ductor-sub-botbuilder",
    )
    events: list[str] = []

    with (
        patch(
            "ductor_bot.infra.docker_rebuild.build_verified_candidate",
            new=AsyncMock(side_effect=lambda *_: events.append("candidate") or candidate),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            side_effect=lambda *_: events.append("inspect-old") or old_id,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.configured_container_names",
            return_value=names,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.tag_image",
            side_effect=lambda *_: events.append("tag-candidate"),
        ) as tag,
        patch(
            "ductor_bot.infra.docker_rebuild.list_direct_image_containers",
            side_effect=lambda *_: events.append("list-old-consumers") or [],
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.remove_containers",
            side_effect=lambda *_: events.append("remove-old-consumers"),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.wait_for_container_images",
            side_effect=lambda *_: events.append("wait-containers"),
        ) as wait,
        patch(
            "ductor_bot.infra.docker_rebuild.verify_container_codex_version",
            side_effect=lambda *_: events.append("verify-container-codex"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_image_tag") as remove_candidate,
    ):
        outcome = await rebuild_docker_image(
            DockerConfig(enabled=True),
            rebuild_paths,
            runtime_was_running=True,
            stop_runtime=lambda: events.append("stop"),
            start_runtime=lambda: events.append("start"),
        )

    assert events == [
        "candidate",
        "inspect-old",
        "stop",
        "tag-candidate",
        "list-old-consumers",
        "remove-old-consumers",
        "start",
        "wait-containers",
        "verify-container-codex",
    ]
    tag.assert_called_once_with(new_id, "ductor-sandbox")
    wait.assert_called_once_with(names, new_id)
    assert outcome.candidate_image_id == new_id
    assert outcome.codex_version == "0.144.6"
    remove_candidate.assert_not_called()


async def test_runtime_verification_failure_restores_old_image_once(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_image import DockerContainerRef
    from ductor_bot.infra.docker_rebuild import CandidateImage, rebuild_docker_image

    old_id = f"sha256:{'a' * 64}"
    new_id = f"sha256:{'b' * 64}"
    candidate = CandidateImage(
        "ductor-sandbox:ductor-candidate-test",
        new_id,
        ProviderCliVersions("2.1.215", "0.144.6", "0.51.0"),
    )
    stop_runtime = Mock()
    start_runtime = Mock()
    candidate_container = DockerContainerRef("new-c1", "ductor-sandbox", new_id)

    def containers(image_id: str) -> list[DockerContainerRef]:
        return [] if image_id == old_id else [candidate_container]

    with (
        patch(
            "ductor_bot.infra.docker_rebuild.build_verified_candidate",
            new=AsyncMock(return_value=candidate),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            return_value=old_id,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.configured_container_names",
            return_value=("ductor-sandbox",),
        ),
        patch("ductor_bot.infra.docker_rebuild.tag_image") as tag,
        patch(
            "ductor_bot.infra.docker_rebuild.list_direct_image_containers",
            side_effect=containers,
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_containers") as remove,
        patch(
            "ductor_bot.infra.docker_rebuild.wait_for_container_images",
            side_effect=RuntimeError("containers did not reach candidate"),
        ),
        pytest.raises(RuntimeError, match="containers did not reach candidate"),
    ):
        await rebuild_docker_image(
            DockerConfig(enabled=True),
            rebuild_paths,
            runtime_was_running=True,
            stop_runtime=stop_runtime,
            start_runtime=start_runtime,
        )

    assert tag.call_args_list == [
        ((new_id, "ductor-sandbox"),),
        ((old_id, "ductor-sandbox"),),
    ]
    assert stop_runtime.call_count == 2
    assert start_runtime.call_count == 2
    remove.assert_any_call([candidate_container])


async def test_promotion_tag_failure_does_not_remove_containers(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import CandidateImage, rebuild_docker_image

    candidate = CandidateImage(
        "ductor-sandbox:ductor-candidate-test",
        f"sha256:{'b' * 64}",
        ProviderCliVersions("2.1.215", "0.144.6", "0.51.0"),
    )
    remove = Mock()
    start_runtime = Mock()
    with (
        patch(
            "ductor_bot.infra.docker_rebuild.build_verified_candidate",
            new=AsyncMock(return_value=candidate),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            return_value=f"sha256:{'a' * 64}",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.configured_container_names",
            return_value=("ductor-sandbox",),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.tag_image",
            side_effect=RuntimeError("Docker tag failed (exit code 9)"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_containers", remove),
        pytest.raises(RuntimeError, match="Docker tag failed"),
    ):
        await rebuild_docker_image(
            DockerConfig(enabled=True),
            rebuild_paths,
            runtime_was_running=True,
            stop_runtime=Mock(),
            start_runtime=start_runtime,
        )

    remove.assert_not_called()
    start_runtime.assert_called_once_with()
