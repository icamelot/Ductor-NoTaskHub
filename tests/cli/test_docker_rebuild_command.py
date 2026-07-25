from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ductor_bot.infra.docker_rebuild import RebuildOutcome


def _docker_data() -> dict[str, object]:
    return {
        "docker": {
            "enabled": True,
            "image_name": "ductor-sandbox",
            "container_name": "ductor-sandbox",
            "extras": ["playwright"],
        }
    }


def test_docker_rebuild_candidate_failure_does_not_stop_or_remove_runtime() -> None:
    from ductor_bot.cli_commands.docker import docker_rebuild

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(None, _docker_data()),
        ),
        patch(
            "ductor_bot.cli_commands.docker._runtime_is_running",
            return_value=True,
            create=True,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.rebuild_docker_image",
            new=AsyncMock(side_effect=RuntimeError("candidate verification failed")),
        ),
        patch("ductor_bot.cli_commands.lifecycle.stop_bot") as stop_bot,
        patch("ductor_bot.cli_commands.docker.subprocess.run") as raw_docker,
        pytest.raises(SystemExit) as exc_info,
    ):
        docker_rebuild()

    assert exc_info.value.code == 1
    stop_bot.assert_not_called()
    raw_docker.assert_not_called()


def test_docker_rebuild_prints_only_safe_acceptance_summary() -> None:
    from ductor_bot.cli_commands.docker import docker_rebuild

    image_id = f"sha256:{'b' * 64}"
    outcome = RebuildOutcome(
        old_image_id=f"sha256:{'a' * 64}",
        candidate_ref="ductor-sandbox:ductor-candidate-test",
        candidate_image_id=image_id,
        codex_version="0.144.6",
    )
    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(Path("/tmp/config.json"), _docker_data()),
        ),
        patch(
            "ductor_bot.cli_commands.docker._runtime_is_running",
            return_value=True,
            create=True,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.rebuild_docker_image",
            new=AsyncMock(return_value=outcome),
        ),
        patch("ductor_bot.cli_commands.docker._console.print") as printer,
        patch("ductor_bot.cli_commands.docker.subprocess.run") as raw_docker,
    ):
        docker_rebuild()

    rendered = "\n".join(str(call.args[0]) for call in printer.call_args_list)
    assert "candidate=ductor-sandbox:ductor-candidate-test" in rendered
    assert f"image={image_id}" in rendered
    assert "codex=0.144.6" in rendered
    raw_docker.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"docker": "invalid"},
        {"docker": {"enabled": False}},
    ],
)
def test_docker_rebuild_invalid_or_disabled_config_exits_one(
    data: dict[str, object],
) -> None:
    from ductor_bot.cli_commands.docker import docker_rebuild

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(Path("/tmp/config.json"), data),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        docker_rebuild()

    assert exc_info.value.code == 1


def test_docker_rebuild_failed_stage_exits_one_without_success_summary() -> None:
    from ductor_bot.cli_commands.docker import docker_rebuild

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(Path("/tmp/config.json"), _docker_data()),
        ),
        patch(
            "ductor_bot.cli_commands.docker._runtime_is_running",
            return_value=True,
            create=True,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.rebuild_docker_image",
            new=AsyncMock(side_effect=RuntimeError("Docker candidate build failed")),
        ),
        patch("ductor_bot.cli_commands.docker._console.print") as printer,
        pytest.raises(SystemExit) as exc_info,
    ):
        docker_rebuild()

    assert exc_info.value.code == 1
    rendered = "\n".join(str(call.args[0]) for call in printer.call_args_list)
    assert "Docker candidate build failed" in rendered
    assert "candidate=" not in rendered
