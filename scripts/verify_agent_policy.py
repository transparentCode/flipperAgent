#!/usr/bin/env python3
"""Mechanically validate agent/MCP policy topology.

The default check is static and does not require running MCP services. ``--live``
adds an opt-in tools/list and forbidden tools/call contract check against the local
per-server adapters.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/agents/mcp-tool-contract.toml"

EXPECTED_URLS = {
    "codebase-memory-mcp": "http://localhost:9748/mcp",
    "gitnexus": "http://localhost:9750/mcp",
}
EXPECTED_CLIENT_SERVER_NAMES = {"hindsight", *EXPECTED_URLS}
EXPECTED_FORBIDDEN = {
    "cbm": {"index_repository", "delete_project", "manage_adr", "ingest_traces"},
    "gitnexus": {"rename", "group_sync"},
}
EXPECTED_POLICY_MODE = "allowlist_default_deny"
EXPECTED_MEMORY_URL = "http://localhost:8888/mcp"
EXPECTED_MEMORY_TOOLS = {
    "list_banks",
    "get_bank",
    "get_bank_stats",
    "create_bank",
    "sync_retain",
    "recall",
    "reflect",
    "list_memories",
    "get_memory",
}
EXPECTED_ROLE_FILES = {
    "quant-architect": ROOT / ".codex/agents/quant-architect.toml",
    "quant-coder": ROOT / ".codex/agents/quant-coder.toml",
}
EXPECTED_ROLE_NAMES = set(EXPECTED_ROLE_FILES)
EXPECTED_REFERENCES = [
    ROOT / "AGENTS.md",
    ROOT / ".agents/skills/mcp-tiered-code-intelligence/SKILL.md",
    ROOT / ".agents/skills/mcp-tiered-code-intelligence/references/cbm-guide.md",
    ROOT / ".agents/skills/quant-orchestrator/SKILL.md",
    ROOT / ".agents/skills/quant-architect/SKILL.md",
    ROOT / ".agents/skills/quant-coder/SKILL.md",
    ROOT / ".agents/skills/quant-orchestrator/references/stage-templates.md",
    ROOT / ".agents/skills/quant-coder/references/coder-checklist.md",
]
EXPECTED_GITHUB_CAPABILITIES = {
    "quant-orchestrator": {
        "codebase-memory-mcp/*",
        "gitnexus/*",
        "hindsight/list_banks",
        "hindsight/get_bank",
        "hindsight/get_bank_stats",
        "hindsight/create_bank",
        "hindsight/sync_retain",
        "hindsight/recall",
        "hindsight/reflect",
        "hindsight/list_memories",
        "hindsight/get_memory",
    },
    "quant-architect": {"codebase-memory-mcp/*", "gitnexus/*"},
    "quant-coder": {"codebase-memory-mcp/*"},
}
SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9][A-Za-z0-9_-]{11,}\b"),
    re.compile(
        r'(?i)"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client_secret|password)"'
        r'\s*:\s*"[^"]{12,}"'
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{16,}\b"),
)


def contains_secret_like_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def check_secret_like_text(path: Path, errors: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path.relative_to(ROOT)}: read failure: {exc}")
        return
    for line_number, line in enumerate(text.splitlines(), start=1):
        if contains_secret_like_text(line):
            errors.append(
                f"{path.relative_to(ROOT)}: secret-like material detected at line {line_number}"
            )


def parse_agent_tools(path: Path, errors: list[str]) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path.relative_to(ROOT)}: read failure: {exc}")
        return set()
    if not text.startswith("---"):
        errors.append(f"{path.relative_to(ROOT)}: YAML front matter missing")
        return set()
    front_matter = text.split("---", 2)[1]
    for line in front_matter.splitlines():
        if not line.strip().startswith("tools:"):
            continue
        raw_list = line.split(":", 1)[1].strip()
        if not (raw_list.startswith("[") and raw_list.endswith("]")):
            errors.append(f"{path.relative_to(ROOT)}: tools metadata must be an inline list")
            return set()
        return {
            item.strip().strip("'\"")
            for item in raw_list[1:-1].split(",")
            if item.strip()
        }
    errors.append(f"{path.relative_to(ROOT)}: tools metadata missing")
    return set()


def load_toml(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: TOML parse/read failure: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)}: TOML root is not a table")
        return {}
    return value


def check_static() -> list[str]:
    errors: list[str] = []
    for path in EXPECTED_REFERENCES:
        if not path.is_file():
            errors.append(f"missing canonical reference: {path.relative_to(ROOT)}")

    contract = load_toml(CONTRACT, errors)
    for field in ("schema_version", "contract_type", "observed_at", "observation_method"):
        value = contract.get(field)
        if not isinstance(value, (str, int)) or value == "":
            errors.append(f"mcp-tool-contract.toml: missing provenance field {field}")
    servers = contract.get("servers", {})
    if not isinstance(servers, dict):
        errors.append("mcp-tool-contract.toml: servers must be a table")
        servers = {}

    config_path = ROOT / ".codex/config.toml"
    config = load_toml(config_path, errors)
    mcp_servers = config.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        errors.append(".codex/config.toml: mcp_servers must be a table")
        mcp_servers = {}
    elif set(mcp_servers) != EXPECTED_CLIENT_SERVER_NAMES:
        errors.append(
            ".codex/config.toml: client-visible MCP server set drifted "
            f"(expected {sorted(EXPECTED_CLIENT_SERVER_NAMES)})"
        )

    agents = config.get("agents", {})
    if not isinstance(agents, dict):
        errors.append(".codex/config.toml: agents must be a table")
    else:
        if agents.get("max_concurrent_threads_per_session") != 2:
            errors.append(
                ".codex/config.toml: agents.max_concurrent_threads_per_session must be 2"
            )
        if "max_threads" in agents:
            errors.append(".codex/config.toml: legacy agents.max_threads is present")

    if "mem0-local" in mcp_servers:
        errors.append(".codex/config.toml: stale mem0-local server registration")
    hindsight = mcp_servers.get("hindsight", {})
    if not isinstance(hindsight, dict):
        errors.append(".codex/config.toml: hindsight must be a table")
    else:
        if hindsight.get("url") != EXPECTED_MEMORY_URL:
            errors.append(".codex/config.toml: hindsight endpoint drifted")
        memory_tools = hindsight.get("enabled_tools", [])
        if set(memory_tools) != EXPECTED_MEMORY_TOOLS:
            errors.append(".codex/config.toml: hindsight.enabled_tools drifted")

    for service, config_name in (("cbm", "codebase-memory-mcp"), ("gitnexus", "gitnexus")):
        contract_server = servers.get(service, {})
        if not isinstance(contract_server, dict):
            errors.append(f"contract server {service!r} must be a table")
            contract_server = {}
        allowed = set(contract_server.get("allowed_tools", []))
        observed = set(contract_server.get("observed_tools", []))
        forbidden = set(contract_server.get("forbidden_tools", []))
        if forbidden != EXPECTED_FORBIDDEN[service]:
            errors.append(f"{service}: contract forbidden_tools drifted")
        if contract_server.get("policy_mode") != EXPECTED_POLICY_MODE:
            errors.append(f"{service}: contract policy_mode must be {EXPECTED_POLICY_MODE}")
        for field in ("adapter_image", "backend_reference", "backend_version"):
            value = contract_server.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{service}: contract missing provenance field {field}")
        if observed != allowed | forbidden:
            errors.append(f"{service}: observed_tools is not allowed_tools union forbidden_tools")
        expected_url = EXPECTED_URLS[config_name]
        if contract_server.get("endpoint") != expected_url:
            errors.append(f"{service}: contract endpoint is not {expected_url}")

        server_config = mcp_servers.get(config_name, {})
        if not isinstance(server_config, dict):
            errors.append(f".codex/config.toml: {config_name} must be a table")
            continue
        if server_config.get("url") != expected_url:
            errors.append(f".codex/config.toml: {config_name} endpoint drifted")
        enabled = server_config.get("enabled_tools", [])
        if not isinstance(enabled, list) or any(not isinstance(item, str) for item in enabled):
            errors.append(f".codex/config.toml: {config_name}.enabled_tools must be a string list")
            continue
        enabled_set = set(enabled)
        if any("*" in item for item in enabled):
            errors.append(f".codex/config.toml: {config_name} uses a wildcard tool allowlist")
        if enabled_set != allowed:
            errors.append(f".codex/config.toml: {config_name}.enabled_tools drifted from allowed_tools")
        overlap = enabled_set & forbidden
        if overlap:
            errors.append(f".codex/config.toml: {config_name} exposes forbidden tools: {sorted(overlap)}")

    role_dir = ROOT / ".codex/agents"
    try:
        actual_role_names = {path.stem for path in role_dir.glob("*.toml")}
    except OSError as exc:
        errors.append(f"{role_dir.relative_to(ROOT)}: read failure: {exc}")
        actual_role_names = set()
    unexpected_roles = actual_role_names - EXPECTED_ROLE_NAMES
    if unexpected_roles:
        errors.append(f"unexpected spawnable Codex roles: {sorted(unexpected_roles)}")

    coder = load_toml(EXPECTED_ROLE_FILES["quant-coder"], errors)
    coder_gitnexus = coder.get("mcp_servers", {}).get("gitnexus", {})
    if (
        not isinstance(coder_gitnexus, dict)
        or coder_gitnexus.get("url") != "http://localhost:9750/mcp"
        or coder_gitnexus.get("enabled") is not False
    ):
        errors.append("quant-coder must disable GitNexus by default")
    for role in ("quant-architect", "quant-coder"):
        role_config = load_toml(EXPECTED_ROLE_FILES[role], errors)
        role_hindsight = role_config.get("mcp_servers", {}).get("hindsight", {})
        if (
            not isinstance(role_hindsight, dict)
            or role_hindsight.get("url") != EXPECTED_MEMORY_URL
            or role_hindsight.get("enabled") is not False
        ):
            errors.append(f"{role} must define and disable Hindsight by default")

    vscode_path = ROOT / ".vscode/mcp.json"
    try:
        vscode = json.loads(vscode_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f".vscode/mcp.json: JSON parse/read failure: {exc}")
        vscode = {}
    vscode_servers = vscode.get("servers", {}) if isinstance(vscode, dict) else {}
    if not isinstance(vscode_servers, dict):
        errors.append(".vscode/mcp.json: servers must be an object")
        vscode_servers = {}
    elif set(vscode_servers) != EXPECTED_CLIENT_SERVER_NAMES:
        errors.append(
            ".vscode/mcp.json: client-visible MCP server set drifted "
            f"(expected {sorted(EXPECTED_CLIENT_SERVER_NAMES)})"
        )
    if "mem0-local" in vscode_servers:
        errors.append(".vscode/mcp.json: stale mem0-local server registration")
    hindsight_vscode = vscode_servers.get("hindsight", {})
    if not isinstance(hindsight_vscode, dict) or hindsight_vscode.get("url") != EXPECTED_MEMORY_URL:
        errors.append(".vscode/mcp.json: hindsight must point to its endpoint")
    for name, expected_url in EXPECTED_URLS.items():
        server = vscode_servers.get(name, {})
        if not isinstance(server, dict) or server.get("url") != expected_url:
            errors.append(f".vscode/mcp.json: {name} must point to its adapter endpoint")

    settings_path = ROOT / ".vscode/settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f".vscode/settings.json: JSON parse/read failure: {exc}")
        settings = {}
    if isinstance(settings, dict):
        if "chat.mcp.serverSampling" in settings:
            errors.append(".vscode/settings.json: generated MCP sampling state must be absent")
        if "chat.mcp.assisted.nuget.enabled" in settings:
            errors.append(".vscode/settings.json: unrelated NuGet MCP setting must be absent")
    check_secret_like_text(settings_path, errors)

    for agent_name in ("quant-orchestrator", "quant-architect", "quant-coder"):
        agent_path = ROOT / f".github/agents/{agent_name}.agent.md"
        agent_tools = parse_agent_tools(agent_path, errors)
        required_tools = EXPECTED_GITHUB_CAPABILITIES[agent_name]
        missing_tools = required_tools - agent_tools
        if missing_tools:
            errors.append(
                f"{agent_path.relative_to(ROOT)}: missing required tools {sorted(missing_tools)}"
            )
        if agent_name == "quant-orchestrator":
            actual_hindsight = {tool for tool in agent_tools if tool.startswith("hindsight/")}
            expected_hindsight = {
                tool for tool in required_tools if tool.startswith("hindsight/")
            }
            if actual_hindsight != expected_hindsight:
                errors.append(
                    f"{agent_path.relative_to(ROOT)}: Hindsight tool set drifted"
                )
        else:
            unexpected_hindsight = {
                tool for tool in agent_tools if tool.startswith("hindsight/")
            }
            if unexpected_hindsight:
                errors.append(
                    f"{agent_path.relative_to(ROOT)}: Hindsight is not allowed for this role"
                )
        if agent_name == "quant-coder":
            unexpected_gitnexus = {
                tool for tool in agent_tools if tool.startswith("gitnexus/")
            }
            if unexpected_gitnexus:
                errors.append(
                    f"{agent_path.relative_to(ROOT)}: GitNexus is not allowed by default"
                )
        if agent_name != "quant-coder" and "gitnexus/*" not in agent_tools:
            errors.append(
                f"{agent_path.relative_to(ROOT)}: GitNexus escalation capability missing"
            )
        try:
            agent_text = agent_path.read_text(encoding="utf-8")
        except OSError:
            agent_text = ""
        if "automem/*" in agent_text:
            errors.append(f"{agent_path.relative_to(ROOT)}: stale Automem wildcard is exposed")
        if "hindsight/*" in agent_text:
            errors.append(f"{agent_path.relative_to(ROOT)}: broad Hindsight wildcard is exposed")

    synthetic_secret = "generated-session::sk-Abcd1234efgh56"
    if not contains_secret_like_text(synthetic_secret):
        errors.append("secret pattern regression: synthetic 14-character sk token was not detected")
    for safe_identifier in ("risk-abcdef12345678", "task-2026-08-22", "model-gpt-5"):
        if contains_secret_like_text(safe_identifier):
            errors.append(
                f"secret pattern regression: ordinary identifier was falsely detected: {safe_identifier}"
            )

    skill_metadata = (ROOT / ".codex/skills/mcp-tiered-code-intelligence.toml").read_text()
    if "mcp_gitnexus_" in skill_metadata:
        errors.append(".codex skill metadata contains stale mcp_gitnexus_* tool names")

    for path in (
        ROOT / "AGENTS.md",
        ROOT / ".codex/config.toml",
        ROOT / ".codex/agents/quant-architect.toml",
        ROOT / ".codex/agents/quant-coder.toml",
        ROOT / ".codex/skills/mcp-tiered-code-intelligence.toml",
        ROOT / ".vscode/mcp.json",
    ):
        check_secret_like_text(path, errors)

    return errors


def check_live() -> list[str]:
    errors: list[str] = []
    external_scripts = ROOT.parent / "mcp" / "scripts"
    if not external_scripts.is_dir():
        return [f"live check unavailable: missing {external_scripts}"]
    sys.path.insert(0, str(external_scripts))
    try:
        from mcp_http import McpHttpError, StreamableHttpSession
    except ImportError as exc:
        return [f"live check unavailable: cannot import mcp_http: {exc}"]

    endpoints = {
        "cbm": "http://127.0.0.1:9748/mcp",
        "gitnexus": "http://127.0.0.1:9750/mcp",
        "hindsight": "http://127.0.0.1:8888/mcp",
    }
    for service, endpoint in endpoints.items():
        session = StreamableHttpSession(endpoint, timeout=15, client_name="agent-policy-check")
        try:
            session.initialize()
            names = {tool.get("name") for tool in session.list_tools() if isinstance(tool, dict)}
            names.discard(None)
            if service == "hindsight":
                expected = EXPECTED_MEMORY_TOOLS
            else:
                contract = load_toml(CONTRACT, errors)
                expected = set(contract["servers"][service]["allowed_tools"])
            if names != expected:
                if service != "hindsight":
                    errors.append(f"live {service}: tools/list mismatch; observed={sorted(names)} expected={sorted(expected)}")
                elif not expected <= names:
                    errors.append(f"live {service}: required memory tools missing; observed={sorted(names)} expected_subset={sorted(expected)}")
            denied_tools = (*EXPECTED_FORBIDDEN[service], "__future_unknown_tool__") if service != "hindsight" else ()
            for forbidden in denied_tools:
                try:
                    session.request("tools/call", {"name": forbidden, "arguments": {}})
                except McpHttpError as exc:
                    if "FORBIDDEN_BY_POLICY" not in str(exc):
                        errors.append(f"live {service}: denied call {forbidden} had wrong error: {exc}")
                else:
                    errors.append(f"live {service}: denied call {forbidden} unexpectedly succeeded")
        except (McpHttpError, OSError, TimeoutError) as exc:
            errors.append(f"live {service}: {exc}")
        finally:
            try:
                session.close()
            except McpHttpError as exc:  # cleanup failure is still a live finding
                errors.append(f"live {service}: session cleanup failed: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="also query both local MCP adapters")
    args = parser.parse_args()

    errors = check_static()
    if args.live:
        errors.extend(check_live())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("agent policy verification passed" + (" (static + live)" if args.live else " (static)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
