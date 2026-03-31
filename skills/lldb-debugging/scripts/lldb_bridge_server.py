#!/usr/bin/env python3
"""LLDB bridge loaded inside Xcode's LLDB process.

This module is designed to be imported via ~/.lldbinit-Xcode:
    command script import /absolute/path/to/lldb_bridge_server.py
"""

from __future__ import annotations

import atexit
import base64
import errno
import json
import os
import queue
import socket
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Callable

try:
    import lldb  # type: ignore
except Exception as exc:  # pragma: no cover - only used inside LLDB
    raise RuntimeError("lldb_bridge_server.py must be imported from LLDB") from exc


ROOT_DIR = os.environ.get("LLDB_BRIDGE_ROOT", "/tmp/lldb-bridge")
SESSIONS_DIR = os.path.join(ROOT_DIR, "sessions")
SOCKETS_DIR = os.path.join(ROOT_DIR, "sockets")
MAX_REQUEST_BYTES = 1_000_000
DEFAULT_DEADLINE_MS = 5_000
MAX_MEMORY_READ_BYTES = 65_536


def _state_name(state: int) -> str:
    text = lldb.SBDebugger.StateAsCString(state)
    return text if text else "unknown"


def _file_spec_to_path(file_spec: Any) -> str | None:
    if not file_spec or not file_spec.IsValid():
        return None
    directory = file_spec.GetDirectory()
    filename = file_spec.GetFilename()
    if directory and filename:
        return os.path.join(directory, filename)
    return filename or directory or None


def _safe_int(value: Any, *, param_name: str) -> tuple[int | None, dict[str, Any] | None]:
    if isinstance(value, bool):
        return None, _error_response("invalid_request", f"'{param_name}' must be an integer")
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        try:
            return int(value, 0), None
        except ValueError:
            return None, _error_response("invalid_request", f"'{param_name}' must be an integer")
    return None, _error_response("invalid_request", f"'{param_name}' must be an integer")


def _coerce_id(raw_id: Any) -> str:
    if isinstance(raw_id, (str, int)):
        return str(raw_id)
    return str(uuid.uuid4())


def _ok_response(request_id: str, result: Any) -> dict[str, Any]:
    return {
        "id": request_id,
        "ok": True,
        "result": result,
    }


def _error_response(code: str, message: str, *, request_id: str | None = None) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if request_id is not None:
        payload["id"] = request_id
    return payload


@dataclass
class _QueuedRequest:
    request_id: str
    method: str
    params: dict[str, Any]
    response_queue: queue.Queue[dict[str, Any]]


class LLDBSocketBridge:
    def __init__(self, debugger: Any):
        self.debugger = debugger
        self.lldb_pid = os.getpid()
        self.session_id = f"{self.lldb_pid}-{uuid.uuid4().hex[:8]}"
        self.socket_path = os.path.join(SOCKETS_DIR, f"{self.session_id}.sock")
        self.session_path = os.path.join(SESSIONS_DIR, f"{self.session_id}.json")

        self._accept_thread: threading.Thread | None = None
        self._execute_thread: threading.Thread | None = None
        self._server_socket: socket.socket | None = None
        self._request_queue: queue.Queue[_QueuedRequest | None] = queue.Queue()
        self._shutdown = threading.Event()
        self._metadata_lock = threading.Lock()
        self._started = False

        self._handlers: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
            "session.info": self._handle_session_info,
            "thread.list": self._handle_thread_list,
            "stack.bt": self._handle_stack_bt,
            "frame.variable": self._handle_frame_variable,
            "expr.eval": self._handle_expr_eval,
            "memory.read": self._handle_memory_read,
        }

    def start(self) -> None:
        if self._started:
            return

        self._prepare_runtime_dirs()

        try:
            if os.path.exists(self.socket_path):
                os.remove(self.socket_path)
        except OSError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        server.listen(16)
        server.settimeout(0.5)
        os.chmod(self.socket_path, 0o600)
        self._server_socket = server

        self._execute_thread = threading.Thread(target=self._execute_loop, name="lldb-bridge-executor", daemon=True)
        self._execute_thread.start()
        self._accept_thread = threading.Thread(target=self._accept_loop, name="lldb-bridge-accept", daemon=True)
        self._accept_thread.start()

        self._started = True
        self._write_session_metadata()
        atexit.register(self.stop)

    def stop(self) -> None:
        if not self._started:
            return

        self._shutdown.set()
        self._request_queue.put(None)

        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None

        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1.0)
            self._accept_thread = None

        if self._execute_thread is not None:
            self._execute_thread.join(timeout=1.0)
            self._execute_thread = None

        try:
            if os.path.exists(self.session_path):
                os.remove(self.session_path)
        except OSError:
            pass

        try:
            if os.path.exists(self.socket_path):
                os.remove(self.socket_path)
        except OSError:
            pass

        self._started = False

    def status_payload(self) -> dict[str, Any]:
        metadata = self._build_session_metadata()
        metadata["bridge_started"] = self._started
        metadata["allowlisted_methods"] = sorted(self._handlers.keys())
        return metadata

    def _prepare_runtime_dirs(self) -> None:
        os.makedirs(ROOT_DIR, mode=0o700, exist_ok=True)
        os.makedirs(SESSIONS_DIR, mode=0o700, exist_ok=True)
        os.makedirs(SOCKETS_DIR, mode=0o700, exist_ok=True)
        for path in (ROOT_DIR, SESSIONS_DIR, SOCKETS_DIR):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass

    def _build_session_metadata(self) -> dict[str, Any]:
        target = self.debugger.GetSelectedTarget()
        target_valid = bool(target and target.IsValid())
        process = target.GetProcess() if target_valid else None
        process_valid = bool(process and process.IsValid())
        process_state = process.GetState() if process_valid else lldb.eStateInvalid

        executable_path = _file_spec_to_path(target.GetExecutable()) if target_valid else None
        executable_name = os.path.basename(executable_path) if executable_path else None
        platform_name = target.GetPlatform().GetName() if target_valid and target.GetPlatform().IsValid() else None
        triple = target.GetTriple() if target_valid else None

        device_kind = "unknown"
        probe = " ".join([str(platform_name or ""), str(triple or ""), str(executable_path or "")]).lower()
        if "simulator" in probe:
            device_kind = "simulator"
        elif "iphoneos" in probe or "device" in probe:
            device_kind = "device"

        return {
            "session_id": self.session_id,
            "socket_path": self.socket_path,
            "lldb_pid": self.lldb_pid,
            "target_executable": executable_path,
            "executable_name": executable_name,
            "process_pid": process.GetProcessID() if process_valid else None,
            "platform_name": platform_name,
            "platform_triple": triple,
            "device_kind": device_kind,
            "state": _state_name(process_state),
            "last_seen_at": time.time(),
            "methods": sorted(self._handlers.keys()),
        }

    def _write_session_metadata(self) -> None:
        metadata = self._build_session_metadata()
        payload = json.dumps(metadata, separators=(",", ":"), sort_keys=True)
        temp_path = f"{self.session_path}.tmp"
        with self._metadata_lock:
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temp_path, self.session_path)
            try:
                os.chmod(self.session_path, 0o600)
            except OSError:
                pass

    def _accept_loop(self) -> None:
        assert self._server_socket is not None
        while not self._shutdown.is_set():
            try:
                conn, _ = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                if self._shutdown.is_set() or exc.errno in {errno.EBADF, errno.EINVAL}:
                    break
                continue
            thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
            thread.start()

    def _execute_loop(self) -> None:
        while not self._shutdown.is_set():
            item = self._request_queue.get()
            if item is None:
                break
            try:
                response = self._dispatch(item.request_id, item.method, item.params)
            except Exception as exc:  # pragma: no cover - defensive safety net
                response = _error_response(
                    "internal_error",
                    f"{type(exc).__name__}: {exc}",
                    request_id=item.request_id,
                )
            try:
                item.response_queue.put_nowait(response)
            except queue.Full:  # pragma: no cover - impossible with maxsize=1
                pass

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(2.0)
            raw = self._read_single_message(conn)
            if raw is None:
                self._send_response(conn, _error_response("invalid_request", "Empty request"))
                return

            request, parse_error = self._parse_request(raw)
            if parse_error is not None:
                self._send_response(conn, parse_error)
                return
            assert request is not None

            request_id = request["id"]
            method = request["method"]
            params = request["params"]
            deadline_ms = request["deadline_ms"]

            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._request_queue.put(_QueuedRequest(request_id=request_id, method=method, params=params, response_queue=response_queue))
            try:
                response = response_queue.get(timeout=max(deadline_ms / 1000.0, 0.01))
            except queue.Empty:
                response = _error_response(
                    "execution_timeout",
                    f"Method '{method}' exceeded deadline of {deadline_ms}ms",
                    request_id=request_id,
                )

            self._send_response(conn, response)

    def _read_single_message(self, conn: socket.socket) -> str | None:
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                data = conn.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            total += len(data)
            if total > MAX_REQUEST_BYTES:
                return None
            chunks.append(data)
            if b"\n" in data:
                break
        if not chunks:
            return None
        payload = b"".join(chunks)
        if b"\n" in payload:
            payload = payload.split(b"\n", 1)[0]
        return payload.decode("utf-8", errors="replace").strip()

    def _parse_request(self, raw: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, _error_response("invalid_request", f"Malformed JSON: {exc}")
        if not isinstance(parsed, dict):
            return None, _error_response("invalid_request", "Request must be a JSON object")

        request_id = _coerce_id(parsed.get("id"))
        method = parsed.get("method")
        params = parsed.get("params", {})
        deadline_ms = parsed.get("deadline_ms", DEFAULT_DEADLINE_MS)

        if not isinstance(method, str) or not method:
            return None, _error_response("invalid_request", "'method' must be a non-empty string", request_id=request_id)
        if not isinstance(params, dict):
            return None, _error_response("invalid_request", "'params' must be an object", request_id=request_id)
        if not isinstance(deadline_ms, int) or deadline_ms <= 0 or deadline_ms > 120_000:
            return None, _error_response("invalid_request", "'deadline_ms' must be an integer between 1 and 120000", request_id=request_id)

        return {
            "id": request_id,
            "method": method,
            "params": params,
            "deadline_ms": deadline_ms,
        }, None

    def _send_response(self, conn: socket.socket, payload: dict[str, Any]) -> None:
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            conn.sendall(data)
        except OSError:
            return

    def _dispatch(self, request_id: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._write_session_metadata()

        handler = self._handlers.get(method)
        if handler is None:
            return _error_response("unknown_method", f"Unsupported method '{method}'", request_id=request_id)
        return handler(request_id, params)

    def _selected_target(self, request_id: str) -> tuple[Any | None, dict[str, Any] | None]:
        target = self.debugger.GetSelectedTarget()
        if not target or not target.IsValid():
            return None, _error_response("session_not_ready", "No selected target in LLDB", request_id=request_id)
        return target, None

    def _selected_process(self, request_id: str) -> tuple[Any | None, dict[str, Any] | None]:
        target, error = self._selected_target(request_id)
        if error is not None:
            return None, error
        process = target.GetProcess()
        if not process or not process.IsValid():
            return None, _error_response("session_not_ready", "No active process in selected target", request_id=request_id)
        return process, None

    def _require_stopped(self, request_id: str) -> tuple[Any | None, dict[str, Any] | None]:
        process, error = self._selected_process(request_id)
        if error is not None:
            return None, error
        state = process.GetState()
        if state not in {lldb.eStateStopped, lldb.eStateCrashed, lldb.eStateSuspended}:
            return None, _error_response(
                "target_not_stopped",
                f"Process state is '{_state_name(state)}'; operation requires a stopped process",
                request_id=request_id,
            )
        return process, None

    def _resolve_thread(self, process: Any, thread_selector: Any, request_id: str) -> tuple[Any | None, dict[str, Any] | None]:
        if thread_selector is None:
            thread = process.GetSelectedThread()
            if thread and thread.IsValid():
                return thread, None
            if process.GetNumThreads() > 0:
                return process.GetThreadAtIndex(0), None
            return None, _error_response("session_not_ready", "Process has no threads", request_id=request_id)

        thread_id, error = _safe_int(thread_selector, param_name="thread")
        if error is not None:
            error["id"] = request_id
            return None, error

        for index in range(process.GetNumThreads()):
            thread = process.GetThreadAtIndex(index)
            if thread.GetThreadID() == thread_id or thread.GetIndexID() == thread_id:
                return thread, None
        return None, _error_response("thread_not_found", f"No thread matched '{thread_selector}'", request_id=request_id)

    def _resolve_frame(self, thread: Any, frame_selector: Any, request_id: str) -> tuple[Any | None, dict[str, Any] | None]:
        if frame_selector is None:
            frame_index = 0
        else:
            frame_index, error = _safe_int(frame_selector, param_name="frame")
            if error is not None:
                error["id"] = request_id
                return None, error

        if frame_index is None or frame_index < 0:
            return None, _error_response("invalid_request", "'frame' must be >= 0", request_id=request_id)

        if frame_index >= thread.GetNumFrames():
            return None, _error_response("frame_not_found", f"Thread has no frame at index {frame_index}", request_id=request_id)
        return thread.GetFrameAtIndex(frame_index), None

    def _serialize_sbvalue(self, value: Any, max_depth: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": value.GetName(),
            "type": value.GetTypeName(),
            "value": value.GetValue(),
            "summary": value.GetSummary(),
            "num_children": value.GetNumChildren(),
            "children": [],
        }
        if max_depth <= 0:
            return payload
        children = []
        num_children = value.GetNumChildren()
        for idx in range(num_children):
            child = value.GetChildAtIndex(idx)
            if not child or not child.IsValid():
                continue
            children.append(self._serialize_sbvalue(child, max_depth=max_depth - 1))
        payload["children"] = children
        return payload

    def _frame_payload(self, frame: Any, index: int) -> dict[str, Any]:
        line_entry = frame.GetLineEntry()
        line = line_entry.GetLine() if line_entry and line_entry.IsValid() else None
        file_path = _file_spec_to_path(line_entry.GetFileSpec()) if line_entry and line_entry.IsValid() else None

        module = frame.GetModule()
        module_path = _file_spec_to_path(module.GetFileSpec()) if module and module.IsValid() else None

        return {
            "index": index,
            "pc": hex(frame.GetPC()),
            "function": frame.GetDisplayFunctionName() or frame.GetFunctionName(),
            "file": file_path,
            "line": line,
            "module": module_path,
        }

    def _handle_session_info(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        del params
        return _ok_response(request_id, self.status_payload())

    def _handle_thread_list(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        del params
        process, error = self._selected_process(request_id)
        if error is not None:
            return error
        selected_thread = process.GetSelectedThread()
        selected_tid = selected_thread.GetThreadID() if selected_thread and selected_thread.IsValid() else None

        threads = []
        for index in range(process.GetNumThreads()):
            thread = process.GetThreadAtIndex(index)
            reason = thread.GetStopDescription(256) if thread.GetStopReason() != lldb.eStopReasonInvalid else None
            threads.append(
                {
                    "index_id": thread.GetIndexID(),
                    "thread_id": thread.GetThreadID(),
                    "name": thread.GetName(),
                    "queue": thread.GetQueueName(),
                    "num_frames": thread.GetNumFrames(),
                    "stop_reason": reason,
                    "selected": thread.GetThreadID() == selected_tid,
                }
            )
        return _ok_response(
            request_id,
            {
                "process_pid": process.GetProcessID(),
                "state": _state_name(process.GetState()),
                "threads": threads,
            },
        )

    def _handle_stack_bt(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        process, error = self._require_stopped(request_id)
        if error is not None:
            return error

        thread, error = self._resolve_thread(process, params.get("thread"), request_id)
        if error is not None:
            return error

        limit = params.get("frame_limit", 64)
        limit_int, error = _safe_int(limit, param_name="frame_limit")
        if error is not None:
            error["id"] = request_id
            return error
        if limit_int is None or limit_int <= 0:
            return _error_response("invalid_request", "'frame_limit' must be > 0", request_id=request_id)

        frame_count = min(limit_int, thread.GetNumFrames())
        frames = [self._frame_payload(thread.GetFrameAtIndex(i), i) for i in range(frame_count)]
        result = {
            "thread": {
                "index_id": thread.GetIndexID(),
                "thread_id": thread.GetThreadID(),
                "name": thread.GetName(),
                "queue": thread.GetQueueName(),
                "num_frames": thread.GetNumFrames(),
            },
            "frames": frames,
        }
        return _ok_response(request_id, result)

    def _handle_frame_variable(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        process, error = self._require_stopped(request_id)
        if error is not None:
            return error

        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error_response("invalid_request", "'name' must be a non-empty string", request_id=request_id)

        thread, error = self._resolve_thread(process, params.get("thread"), request_id)
        if error is not None:
            return error
        frame, error = self._resolve_frame(thread, params.get("frame"), request_id)
        if error is not None:
            return error

        max_depth = params.get("max_depth", 1)
        max_depth_int, error = _safe_int(max_depth, param_name="max_depth")
        if error is not None:
            error["id"] = request_id
            return error
        if max_depth_int is None or max_depth_int < 0 or max_depth_int > 10:
            return _error_response("invalid_request", "'max_depth' must be between 0 and 10", request_id=request_id)

        variable = frame.FindVariable(name)
        if not variable or not variable.IsValid():
            variable = frame.FindValue(name, lldb.eValueTypeVariableGlobal)
        if not variable or not variable.IsValid():
            return _error_response("variable_not_found", f"No variable named '{name}' in selected frame", request_id=request_id)

        return _ok_response(
            request_id,
            {
                "thread_id": thread.GetThreadID(),
                "frame_index": frame.GetFrameID(),
                "variable": self._serialize_sbvalue(variable, max_depth=max_depth_int),
            },
        )

    def _handle_expr_eval(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        process, error = self._require_stopped(request_id)
        if error is not None:
            return error

        expression = params.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            return _error_response("invalid_request", "'expression' must be a non-empty string", request_id=request_id)

        thread, error = self._resolve_thread(process, params.get("thread"), request_id)
        if error is not None:
            return error
        frame, error = self._resolve_frame(thread, params.get("frame"), request_id)
        if error is not None:
            return error

        options = lldb.SBExpressionOptions()
        options.SetIgnoreBreakpoints(True)
        options.SetTrapExceptions(False)
        options.SetTimeoutInMicroSeconds(2_000_000)
        options.SetTryAllThreads(False)

        value = frame.EvaluateExpression(expression, options)
        if not value or not value.IsValid():
            return _error_response("evaluation_failed", "Expression evaluation returned no value", request_id=request_id)

        error_obj = value.GetError()
        if error_obj and error_obj.Fail():
            return _error_response("evaluation_failed", error_obj.GetCString() or "Expression evaluation failed", request_id=request_id)

        max_depth = params.get("max_depth", 1)
        max_depth_int, err = _safe_int(max_depth, param_name="max_depth")
        if err is not None:
            err["id"] = request_id
            return err
        if max_depth_int is None or max_depth_int < 0 or max_depth_int > 10:
            return _error_response("invalid_request", "'max_depth' must be between 0 and 10", request_id=request_id)

        return _ok_response(
            request_id,
            {
                "thread_id": thread.GetThreadID(),
                "frame_index": frame.GetFrameID(),
                "result": self._serialize_sbvalue(value, max_depth=max_depth_int),
            },
        )

    def _handle_memory_read(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        process, error = self._require_stopped(request_id)
        if error is not None:
            return error

        if "address" not in params:
            return _error_response("invalid_request", "'address' is required", request_id=request_id)
        if "size" not in params:
            return _error_response("invalid_request", "'size' is required", request_id=request_id)

        address, error = _safe_int(params["address"], param_name="address")
        if error is not None:
            error["id"] = request_id
            return error
        size, error = _safe_int(params["size"], param_name="size")
        if error is not None:
            error["id"] = request_id
            return error

        if address is None or address < 0:
            return _error_response("invalid_request", "'address' must be >= 0", request_id=request_id)
        if size is None or size <= 0:
            return _error_response("invalid_request", "'size' must be > 0", request_id=request_id)
        if size > MAX_MEMORY_READ_BYTES:
            return _error_response(
                "invalid_request",
                f"'size' must be <= {MAX_MEMORY_READ_BYTES} bytes",
                request_id=request_id,
            )

        error_obj = lldb.SBError()
        data = process.ReadMemory(address, size, error_obj)
        if error_obj.Fail():
            return _error_response("memory_read_failed", error_obj.GetCString() or "Memory read failed", request_id=request_id)

        raw = bytes(data) if data is not None else b""
        return _ok_response(
            request_id,
            {
                "address": address,
                "size": len(raw),
                "data_base64": base64.b64encode(raw).decode("ascii"),
                "data_hex": raw.hex(),
            },
        )


_BRIDGE: LLDBSocketBridge | None = None


def bridge_start(debugger: Any | None = None) -> LLDBSocketBridge:
    global _BRIDGE
    if _BRIDGE is not None:
        return _BRIDGE
    if debugger is None:
        debugger = lldb.debugger
    bridge = LLDBSocketBridge(debugger)
    bridge.start()
    _BRIDGE = bridge
    print(f"[lldb-bridge] started session={bridge.session_id} socket={bridge.socket_path}")
    return bridge


def bridge_stop() -> None:
    global _BRIDGE
    if _BRIDGE is None:
        return
    _BRIDGE.stop()
    print(f"[lldb-bridge] stopped session={_BRIDGE.session_id}")
    _BRIDGE = None


def _cmd_bridge_status(debugger: Any, command: str, exe_ctx: Any, result: Any, _internal_dict: dict[str, Any]) -> None:
    del debugger, command, exe_ctx
    if _BRIDGE is None:
        result.PutCString("lldb-bridge: not started")
        return
    status = json.dumps(_BRIDGE.status_payload(), indent=2, sort_keys=True)
    result.PutCString(status)


def _cmd_bridge_start(debugger: Any, command: str, exe_ctx: Any, result: Any, _internal_dict: dict[str, Any]) -> None:
    del command, exe_ctx
    bridge = bridge_start(debugger)
    result.PutCString(f"lldb-bridge started: session={bridge.session_id}")


def _cmd_bridge_stop(debugger: Any, command: str, exe_ctx: Any, result: Any, _internal_dict: dict[str, Any]) -> None:
    del debugger, command, exe_ctx
    bridge_stop()
    result.PutCString("lldb-bridge stopped")


def __lldb_init_module(debugger: Any, _internal_dict: dict[str, Any]) -> None:  # pragma: no cover - LLDB entrypoint
    debugger.HandleCommand("command script add -f lldb_bridge_server._cmd_bridge_status lldb-bridge-status")
    debugger.HandleCommand("command script add -f lldb_bridge_server._cmd_bridge_start lldb-bridge-start")
    debugger.HandleCommand("command script add -f lldb_bridge_server._cmd_bridge_stop lldb-bridge-stop")

    auto_start = os.environ.get("LLDB_BRIDGE_AUTOSTART", "1")
    if auto_start == "1":
        try:
            bridge_start(debugger)
        except Exception:
            traceback.print_exc()
