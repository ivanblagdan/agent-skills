#!/usr/bin/env python3
"""CLI for the LLDB bridge."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any


ROOT_DIR = os.environ.get("LLDB_BRIDGE_ROOT", "/tmp/lldb-bridge")
DEFAULT_DEADLINE_MS = 5_000
MAX_RESPONSE_BYTES = 5_000_000


class CLIError(Exception):
    def __init__(self, code: str, message: str, *, detail: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass
class SessionSelectors:
    session_id: str | None
    bundle: str | None
    pid: int | None
    device_kind: str | None


def _load_sessions(*, prune_stale: bool = True) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    sessions_dir = os.path.join(ROOT_DIR, "sessions")
    if not os.path.isdir(sessions_dir):
        return sessions

    for name in sorted(os.listdir(sessions_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(sessions_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                session = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue

        socket_path = session.get("socket_path")
        if not isinstance(socket_path, str):
            continue
        alive = os.path.exists(socket_path)
        if not alive and prune_stale:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        session["alive"] = alive
        session["_session_file"] = path
        sessions.append(session)
    return sessions


def _match_bundle(session: dict[str, Any], bundle_query: str) -> bool:
    query = bundle_query.lower()
    candidates = [
        str(session.get("target_executable") or "").lower(),
        str(session.get("executable_name") or "").lower(),
    ]
    return any(query in candidate for candidate in candidates)


def _resolve_session(selectors: SessionSelectors) -> dict[str, Any]:
    sessions = _load_sessions(prune_stale=True)
    if not sessions:
        raise CLIError("no_sessions", "No active LLDB bridge sessions were found.")

    candidates = sessions
    if selectors.session_id:
        candidates = [s for s in candidates if s.get("session_id") == selectors.session_id]
        if not candidates:
            raise CLIError("session_not_found", f"Session '{selectors.session_id}' not found.")
        return candidates[0]

    if selectors.bundle:
        candidates = [s for s in candidates if _match_bundle(s, selectors.bundle)]
    if selectors.pid is not None:
        candidates = [s for s in candidates if s.get("process_pid") == selectors.pid]
    if selectors.device_kind:
        candidates = [s for s in candidates if s.get("device_kind") == selectors.device_kind]

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 0:
        raise CLIError(
            "session_not_found",
            "No sessions matched selectors.",
            detail={
                "bundle": selectors.bundle,
                "pid": selectors.pid,
                "device_kind": selectors.device_kind,
            },
        )

    if len(sessions) == 1 and not any([selectors.bundle, selectors.pid, selectors.device_kind]):
        return sessions[0]

    raise CLIError(
        "ambiguous_session",
        "Multiple sessions matched. Pass --session to choose one.",
        detail=[
            {
                "session_id": s.get("session_id"),
                "process_pid": s.get("process_pid"),
                "state": s.get("state"),
                "device_kind": s.get("device_kind"),
                "target_executable": s.get("target_executable"),
            }
            for s in candidates
        ],
    )


def _normalize_method(method: str) -> str:
    aliases = {
        "expr": "expr.eval",
        "bt": "stack.bt",
        "frame-variable": "frame.variable",
        "frame_variable": "frame.variable",
        "memory-read": "memory.read",
        "memory_read": "memory.read",
        "threads": "thread.list",
    }
    return aliases.get(method, method)


def _send_request(socket_path: str, request: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    payload = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s)
        conn.connect(socket_path)
        conn.sendall(payload)
        conn.shutdown(socket.SHUT_WR)

        chunks: list[bytes] = []
        total = 0
        while True:
            data = conn.recv(4096)
            if not data:
                break
            total += len(data)
            if total > MAX_RESPONSE_BYTES:
                raise CLIError("response_too_large", "Bridge response exceeded size limit.")
            chunks.append(data)
            if b"\n" in data:
                break

    if not chunks:
        raise CLIError("empty_response", "Bridge returned an empty response.")

    raw = b"".join(chunks)
    if b"\n" in raw:
        raw = raw.split(b"\n", 1)[0]
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise CLIError("malformed_response", f"Bridge returned invalid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise CLIError("malformed_response", "Bridge returned a non-object JSON response.")
    return decoded


def _format_session_row(session: dict[str, Any]) -> str:
    sid = session.get("session_id", "unknown")
    state = session.get("state", "unknown")
    pid = session.get("process_pid")
    kind = session.get("device_kind", "unknown")
    exe = session.get("target_executable") or session.get("executable_name") or "-"
    return f"{sid}  pid={pid}  state={state}  device={kind}  exe={exe}"


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _selectors_from_args(args: argparse.Namespace) -> SessionSelectors:
    return SessionSelectors(
        session_id=getattr(args, "session", None),
        bundle=getattr(args, "bundle", None),
        pid=getattr(args, "pid", None),
        device_kind=getattr(args, "device_kind", None),
    )


def _add_selector_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session", help="Exact session id")
    parser.add_argument("--bundle", help="Substring match against executable path/name")
    parser.add_argument("--pid", type=int, help="Process PID")
    parser.add_argument("--device-kind", choices=["simulator", "device", "unknown"], help="Device kind")


def _command_list(args: argparse.Namespace) -> int:
    sessions = _load_sessions(prune_stale=True)
    sessions.sort(key=lambda session: session.get("last_seen_at", 0), reverse=True)
    if args.json:
        _print_json(sessions)
    else:
        if not sessions:
            print("No active LLDB bridge sessions.")
            return 1
        for session in sessions:
            print(_format_session_row(session))
    return 0


def _command_inspect(args: argparse.Namespace) -> int:
    session = _resolve_session(_selectors_from_args(args))
    request = {
        "id": str(uuid.uuid4()),
        "method": "session.info",
        "params": {},
        "deadline_ms": max(args.deadline_ms, 1),
    }
    timeout_s = max((args.deadline_ms / 1000.0) + 1.0, 1.0)
    response = _send_request(session["socket_path"], request, timeout_s=timeout_s)

    if args.json:
        _print_json(response)
    else:
        if response.get("ok"):
            _print_json(response.get("result"))
        else:
            _print_json(response)
            return 2
    return 0


def _command_exec(args: argparse.Namespace) -> int:
    session = _resolve_session(_selectors_from_args(args))
    method = _normalize_method(args.method)

    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            raise CLIError("invalid_params", f"--params must be valid JSON: {exc}") from exc
        if not isinstance(params, dict):
            raise CLIError("invalid_params", "--params JSON must be an object.")
    else:
        params = {}

    request = {
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
        "deadline_ms": max(args.deadline_ms, 1),
    }
    timeout_s = max((args.deadline_ms / 1000.0) + 2.0, 2.0)
    response = _send_request(session["socket_path"], request, timeout_s=timeout_s)

    if args.json:
        _print_json(response)
    else:
        if response.get("ok"):
            _print_json(response.get("result"))
        else:
            code = response.get("error", {}).get("code", "error")
            message = response.get("error", {}).get("message", "Unknown error")
            print(f"{code}: {message}", file=sys.stderr)
            return 2

    return 0 if response.get("ok") else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lldb-bridge", description="CLI client for the LLDB bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_list = subparsers.add_parser("list", help="List active LLDB bridge sessions")
    parser_list.add_argument("--json", action="store_true", help="Output JSON")
    parser_list.set_defaults(func=_command_list)

    parser_inspect = subparsers.add_parser("inspect", help="Inspect one resolved session")
    _add_selector_flags(parser_inspect)
    parser_inspect.add_argument("--deadline-ms", type=int, default=DEFAULT_DEADLINE_MS, help="Request deadline")
    parser_inspect.add_argument("--json", action="store_true", help="Output JSON")
    parser_inspect.set_defaults(func=_command_inspect)

    parser_exec = subparsers.add_parser("exec", help="Execute one method against a resolved session")
    _add_selector_flags(parser_exec)
    parser_exec.add_argument("method", help="Bridge method, e.g. expr.eval / frame.variable / stack.bt")
    parser_exec.add_argument("--params", help="JSON object for method params", default="{}")
    parser_exec.add_argument("--deadline-ms", type=int, default=DEFAULT_DEADLINE_MS, help="Request deadline")
    parser_exec.add_argument("--json", action="store_true", help="Output JSON")
    parser_exec.set_defaults(func=_command_exec)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        start = time.time()
        code = args.func(args)
        elapsed_ms = int((time.time() - start) * 1000)
        if getattr(args, "json", False):
            # Keep stdout machine-readable when --json is used.
            pass
        elif os.environ.get("LLDB_BRIDGE_VERBOSE") == "1":
            print(f"[lldb-bridge] completed in {elapsed_ms}ms", file=sys.stderr)
        return code
    except CLIError as exc:
        payload = {
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        }
        if exc.detail is not None:
            payload["error"]["detail"] = exc.detail

        if getattr(args, "json", False):
            _print_json(payload)
        else:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
            if exc.detail is not None:
                print(json.dumps(exc.detail, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
