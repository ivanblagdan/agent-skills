---
name: lldb-debugging
description: Install and use a local LLDB bridge for live Xcode debugging sessions. Use when you need to inspect app state (stack, variables, expressions, memory) without manual copy/paste from Xcode.
---

# LLDB Debugging

Use this skill to connect to an active Xcode LLDB session through a local Unix socket bridge.

## Files In This Skill

- `scripts/lldb_bridge_server.py`: loaded inside Xcode LLDB (`~/.lldbinit-Xcode`).
- `scripts/lldb_bridge_cli.py`: CLI client used by the agent.

## Install

1. Add this line to `~/.lldbinit-Xcode`:
`command script import /ABS/PATH/TO/.agents/skills/lldb-debugging/scripts/lldb_bridge_server.py`
2. Start a debug session in Xcode.
3. In LLDB console, verify:
`lldb-bridge-status`

## Usage

1. List sessions:
`python3 /ABS/PATH/TO/.agents/skills/lldb-debugging/scripts/lldb_bridge_cli.py list --json`
2. Inspect one session:
`python3 /ABS/PATH/TO/.agents/skills/lldb-debugging/scripts/lldb_bridge_cli.py inspect --session <session_id> --json`
3. Execute methods:
- `thread.list`
- `stack.bt` (alias: `bt`)
- `frame.variable` (alias: `frame-variable`)
- `expr.eval` (alias: `expr`)
- `memory.read` (alias: `memory-read`)

Example:
`python3 /ABS/PATH/TO/.agents/skills/lldb-debugging/scripts/lldb_bridge_cli.py exec --session <session_id> bt --params '{"frame_limit":12}' --json`

## Mechanics And Data Flow

1. Xcode loads `scripts/lldb_bridge_server.py` into the live LLDB process.
2. The bridge opens a per-session Unix socket under `/tmp/lldb-bridge/sockets`.
3. The bridge writes session metadata under `/tmp/lldb-bridge/sessions`.
4. CLI resolves a session and sends a JSON request.
5. Bridge executes allowlisted LLDB operations and returns structured JSON.

## Troubleshooting

- `no_sessions`:
Ensure Xcode loaded `~/.lldbinit-Xcode` and run `lldb-bridge-status` in LLDB.
- `PermissionError: Operation not permitted` on socket connect:
Run CLI with elevated permissions in sandboxed environments.
- `target_not_stopped`:
Pause execution in LLDB before running `stack.bt`, `frame.variable`, `expr.eval`, or `memory.read`.
- `ambiguous_session`:
Pass `--session <session_id>` explicitly.
- `unknown_method`:
Use supported method names above.
