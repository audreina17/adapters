"""Parent-owned lifetime and per-request resource limits for isolated workers."""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import select
import selectors
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_RESPONSE_BYTES = 16 * 1024**2


class Worker:
    def __init__(self, command=None):
        if sys.platform.startswith("linux"):
            # Adopt runuser's child so killing the group cannot leave zombies.
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
                raise OSError(ctypes.get_errno(), "cannot enable child reaping")
        self.process = subprocess.Popen(
            command
            or [
                "/usr/sbin/runuser",
                "--user",
                "sandbox",
                "--",
                "python",
                "/app/persistent_worker.py",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONNOUSERSITE": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
            },
        )
        os.set_blocking(self.process.stdin.fileno(), False)
        self.lock = threading.RLock()
        self.last_used = time.monotonic()
        self.closed = False
        self.cpu_seen = {}
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def cpu_seconds(self):
        if not sys.platform.startswith("linux"):
            return 0.0
        # Include the runuser child and any descendants in the owned group.
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = path.read_text().rsplit(")", 1)[1].split()
                if int(fields[2]) == self.process.pid:
                    identity = (path.parent.name, fields[19])
                    ticks = int(fields[11]) + int(fields[12])
                    self.cpu_seen[identity] = max(ticks, self.cpu_seen.get(identity, 0))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        return sum(self.cpu_seen.values()) / os.sysconf("SC_CLK_TCK")

    def request(self, request, timeout=15.0, cpu_budget=12.0):
        with self.lock:
            if self.closed:
                raise RuntimeError("law worker is closed")
            deadline = time.monotonic() + timeout
            initial_cpu = self.cpu_seconds()
            try:
                payload = memoryview((json.dumps(request) + "\n").encode())
                while payload:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or self.cpu_seconds() - initial_cpu >= cpu_budget:
                        raise subprocess.TimeoutExpired("law worker", timeout)
                    if select.select(
                        [], [self.process.stdin], [], min(remaining, 0.05)
                    )[1]:
                        try:
                            written = os.write(self.process.stdin.fileno(), payload)
                            payload = payload[written:]
                        except BlockingIOError:
                            continue
                output = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or self.cpu_seconds() - initial_cpu >= cpu_budget:
                        raise subprocess.TimeoutExpired("law worker", timeout)
                    if not self.selector.select(min(remaining, 0.05)):
                        continue
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError("law worker exited without a response")
                    output.extend(chunk)
                    if len(output) > MAX_RESPONSE_BYTES:
                        raise ValueError("law worker response exceeds size limit")
                    if b"\n" in output:
                        response = json.loads(output)
                        break
            except BaseException:
                self.close()
                raise
            finally:
                self.last_used = time.monotonic()
            if not response.get("ok"):
                raise ValueError(response.get("error", "law execution failed"))
            return response["result"]

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # macOS may deny signaling a group whose sole child exited.
                if sys.platform != "darwin" or self.process.poll() is None:
                    raise
            self.process.wait()
            while True:
                try:
                    os.waitpid(-self.process.pid, 0)
                except ChildProcessError:
                    break
            self.selector.close()
            self.process.stdin.close()
            self.process.stdout.close()


class Sessions:
    def __init__(self, command=None):
        self.command = command
        self.workers = {}
        self.lock = threading.RLock()

    def create(self, source, kind):
        if kind not in ("law", "fit"):
            raise ValueError("invalid compilation kind")
        with self.lock:
            if len(self.workers) >= 16:
                raise ValueError("too many law sessions")
            worker = Worker(self.command)
            identifier = secrets.token_hex(24)
            self.workers[identifier] = worker
        try:
            result = worker.request(
                {"action": "compile", "source": source, "kind": kind}, timeout=15
            )
            return {"session": identifier, **result}
        except BaseException:
            self.close(identifier)
            raise

    def request(self, identifier, body):
        with self.lock:
            worker = self.workers[identifier]
        return worker.request(body)

    def close(self, identifier):
        with self.lock:
            worker = self.workers.pop(identifier, None)
        if worker is not None:
            worker.close()

    def reap_idle(self, idle_seconds=300):
        with self.lock:
            for identifier, worker in list(self.workers.items()):
                if worker.lock.acquire(blocking=False):
                    try:
                        if time.monotonic() - worker.last_used > idle_seconds:
                            self.close(identifier)
                    finally:
                        worker.lock.release()

    def close_all(self):
        with self.lock:
            for identifier in list(self.workers):
                self.close(identifier)
