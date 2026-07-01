"""Tests for the runtime self-modification write gate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from model_tools import handle_function_call


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _blocked_call(function_name: str, args: dict, user_task: str):
    with patch("hermes_cli.plugins.has_hook", return_value=False), patch(
        "model_tools.registry.dispatch",
        side_effect=AssertionError("dispatch should not run for blocked self-modification"),
    ):
        return json.loads(
            handle_function_call(
                function_name,
                args,
                task_id="task-1",
                user_task=user_task,
                skip_pre_tool_call_hook=True,
                skip_tool_request_middleware=True,
            )
        )


class TestSelfModificationGuard:
    def test_ordinary_task_cannot_mutate_protected_skill_path(self):
        target = _repo_root() / "skills/productivity/notion/SKILL.md"
        result = _blocked_call(
            "write_file",
            {"path": str(target), "content": "patched"},
            "Please update the launch checklist.",
        )
        assert "error" in result
        assert "self-modification" in result["error"].lower()
        assert "explicit user instruction" in result["error"].lower()

    def test_explicit_self_improvement_request_can_pass(self):
        target = _repo_root() / "skills/autonomous-ai-agents/hermes-agent/SKILL.md"
        with patch("hermes_cli.plugins.has_hook", return_value=False), patch(
            "model_tools.registry.dispatch",
            return_value='{"ok": true}',
        ) as dispatch:
            result = handle_function_call(
                "write_file",
                {"path": str(target), "content": "patched"},
                task_id="task-2",
                user_task=f"Explicit self-improvement request: edit the target file {target} and validate it.",
                skip_pre_tool_call_hook=True,
                skip_tool_request_middleware=True,
            )
        assert result == '{"ok": true}'
        dispatch.assert_called_once()

    def test_blocked_tool_call_does_not_execute_terminal_write(self):
        target = _repo_root() / "docs/hermes-guardrails.md"
        result = _blocked_call(
            "terminal",
            {"command": f"cat > {target} <<'EOF'\nmutated\nEOF"},
            "Please improve the launch notes.",
        )
        assert "error" in result
        assert "terminal" in result["error"].lower()

    def test_blocked_shell_redirection_without_space_is_detected(self):
        target = _repo_root() / "docs/hermes-guardrails.md"
        result = _blocked_call(
            "terminal",
            {"command": f"echo mutated >{target}"},
            "Please improve the launch notes.",
        )
        assert "error" in result
        assert target.name.lower() in result["error"].lower()
        assert "blocked self-modification" in result["error"].lower()

    def test_skill_manage_is_blocked_for_unrequested_skill_writes(self):
        result = _blocked_call(
            "skill_manage",
            {"action": "update", "name": "notion", "category": "productivity"},
            "Please improve the launch notes.",
        )
        assert "error" in result
        assert "skill_manage" in result["error"].lower()
        assert "protected path" in result["error"].lower()

    def test_notion_healthcheck_cannot_mutate_notion_skill_files(self):
        target = _repo_root() / "skills/productivity/notion/SKILL.md"
        result = _blocked_call(
            "write_file",
            {"path": str(target), "content": "healthcheck mutation"},
            "Run a Notion healthcheck.",
        )
        assert "error" in result
        assert "notion" in str(target).lower()
        assert "blocked self-modification" in result["error"].lower()
