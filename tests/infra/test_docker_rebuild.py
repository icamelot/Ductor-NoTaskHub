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
