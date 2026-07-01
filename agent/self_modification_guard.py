"""Self-modification write guardrails for Hermes control paths."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

_PROTECTED_ROOT_NAMES = frozenset({
    "skills",
    "profiles",
    "docs",
    "hooks",
    "scripts",
    ".github",
})

_PROTECTED_EXACT_FILES = frozenset({
    "config.yaml",
    "config.example.yaml",
})

_WRITE_TOOL_NAMES = frozenset({"write_file", "patch", "skill_manage"})
_TERMINAL_TOOL_NAMES = frozenset({"terminal"})
_EXECUTE_CODE_TOOL_NAMES = frozenset({"execute_code"})

_SELF_IMPROVEMENT_HINTS = (
    r"\bself[- ]?improv(?:e|ement)\b",
    r"\bconfig(?:uration)?\s+edit(?:ing)?\b",
    r"\bskill\s+edit(?:ing)?\b",
    r"\bguardrail\s+work\b",
    r"\brepo/config\s+editing\b",
    r"\bedit(?:ing)?\s+(?:the\s+)?(?:hermes\s+)?config\b",
    r"\bedit(?:ing)?\b",
    r"\bupdate(?:ing)?\b",
    r"\bmodify(?:ing)?\b",
    r"\bchange(?:ing)?\b",
    r"\bpatch(?:ing)?\b",
    r"\bfix(?:ing)?\b",
    r"\bcreate(?:d|ing)?\b",
    r"\bdelete(?:d|ing)?\b",
    r"\bremove(?:d|ing)?\b",
    r"\badd(?:ed|ing)?\b",
    r"\brewrite(?:ing)?\b",
    r"\brefactor(?:ing)?\b",
    r"\bharden(?:ing)?\b",
)

_SHELL_WRITE_HINTS = (
    r">>",
    r">",
    r"\btee\b",
    r"\bsed\s+-i\b",
    r"\bperl\s+-pi\b",
    r"\bcp\b",
    r"\bmv\b",
    r"\brm\b",
    r"\btouch\b",
)

_CODE_WRITE_HINTS = (
    r"\bopen\s*\([^)]*['\"](?:w|a|x|\+)",
    r"\.write_text\s*\(",
    r"\.write_bytes\s*\(",
    r"\.unlink\s*\(",
    r"\.rename\s*\(",
    r"\.replace\s*\(",
    r"\bos\.(?:remove|unlink|rename)\s*\(",
    r"\bshutil\.(?:move|copy|copy2)\s*\(",
)


def before_tool_call(function_name: str, function_args: Mapping[str, Any] | None, user_task: str | None) -> str | None:
    """Return a block message when a tool would mutate Hermes control files."""
    args = function_args if isinstance(function_args, Mapping) else {}
    user_task_text = str(user_task or "").strip()

    if function_name in _WRITE_TOOL_NAMES:
        targets = _candidate_targets(function_name, args)
        protected_targets = [target for target in targets if _is_protected_path(target)]
        if not protected_targets:
            return None
        if _is_explicit_self_mod_request(user_task_text, protected_targets):
            return None
        return _blocked_message(function_name, protected_targets)

    if function_name in _TERMINAL_TOOL_NAMES:
        command = str(args.get("command") or args.get("cmd") or "").strip()
        if not command:
            return None
        protected_targets = _extract_protected_mentions(command)
        if not protected_targets or not _contains_write_intent(command):
            return None
        if _is_explicit_self_mod_request(user_task_text, protected_targets):
            return None
        return _blocked_message(function_name, protected_targets)

    if function_name in _EXECUTE_CODE_TOOL_NAMES:
        code = str(args.get("code") or "").strip()
        if not code:
            return None
        protected_targets = _extract_protected_mentions(code)
        if not protected_targets or not _contains_code_write_intent(code):
            return None
        if _is_explicit_self_mod_request(user_task_text, protected_targets):
            return None
        return _blocked_message(function_name, protected_targets)

    return None


def _blocked_message(function_name: str, protected_targets: Sequence[str]) -> str:
    unique_targets = list(dict.fromkeys(protected_targets))
    target_text = ", ".join(unique_targets[:4])
    if len(unique_targets) > 4:
        target_text += f", +{len(unique_targets) - 4} more"
    return (
        f"Blocked self-modification write via {function_name} for protected path(s): {target_text}. "
        "This requires explicit user instruction naming the target files; propose the change instead."
    )


def _first_path_arg(args: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _candidate_targets(function_name: str, args: Mapping[str, Any]) -> list[str]:
    if function_name == "skill_manage":
        targets: list[str] = []
        file_path = _first_path_arg(args, ("file_path", "path", "filepath"))
        if file_path:
            targets.append(file_path)
        name = str(args.get("name") or "").strip()
        category = str(args.get("category") or "").strip()
        if name:
            if category:
                targets.extend([
                    f"skills/{category}/{name}/SKILL.md",
                    f"skills/{category}/{name}.md",
                ])
            targets.extend([
                f"skills/{name}/SKILL.md",
                f"skills/{name}.md",
            ])
        return targets
    return [
        target
        for target in (
            _first_path_arg(args, ("path", "filepath", "file_path", "target")),
        )
        if target
    ]


def _is_protected_path(path_text: str) -> bool:
    text = str(path_text or "").replace("\\", "/").strip()
    if not text:
        return False
    lower = text.lower()
    if any(exact == lower.rsplit("/", 1)[-1] for exact in _PROTECTED_EXACT_FILES):
        return True
    path = Path(text)
    parts = [part.lower() for part in path.parts]
    if any(part in _PROTECTED_ROOT_NAMES for part in parts):
        return True
    return any(f"/{root}/" in f"/{lower}" for root in _PROTECTED_ROOT_NAMES)


def _extract_protected_mentions(text: str) -> list[str]:
    if not text:
        return []
    normalized = text.replace("\\", "/")
    lower = normalized.lower()
    mentions: list[str] = []
    for exact in _PROTECTED_EXACT_FILES:
        if exact in lower:
            mentions.append(exact)
    for root in _PROTECTED_ROOT_NAMES:
        marker = f"{root}/"
        start = 0
        while True:
            idx = lower.find(marker, start)
            if idx < 0:
                break
            end = idx + len(marker)
            while end < len(normalized) and normalized[end] not in " \t\r\n'\"`|&;<>":
                end += 1
            mentions.append(normalized[idx:end].rstrip(".,);]"))
            start = end
    return list(dict.fromkeys(mentions))


def _is_explicit_self_mod_request(user_task: str, protected_targets: Sequence[str]) -> bool:
    if not user_task or not protected_targets:
        return False
    lower = user_task.lower()
    if not any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in _SELF_IMPROVEMENT_HINTS):
        return False

    target_tokens = set()
    for target in protected_targets:
        normalized = str(target).replace("\\", "/").strip().lower()
        if not normalized:
            continue
        target_tokens.add(normalized)
        try:
            path = Path(normalized)
        except Exception:
            path = None
        if path is not None:
            parts = [part.lower() for part in path.parts if part]
            for i in range(len(parts)):
                target_tokens.add("/".join(parts[i:]))
            if parts:
                target_tokens.add(parts[-1])
    return any(token and token in lower for token in target_tokens)


def _contains_write_intent(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _SHELL_WRITE_HINTS + _CODE_WRITE_HINTS)


def _contains_code_write_intent(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _CODE_WRITE_HINTS + _SHELL_WRITE_HINTS)
