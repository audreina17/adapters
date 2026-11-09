"""Unprivileged, session-scoped law execution; supervised by the runner process."""

from __future__ import annotations

import contextlib
import functools
import json
import os
import sys
from collections.abc import Callable

from execute_law import jsonable

LAW_CALL_TIMEOUT_S = 10.0


class _LawCallTimeout(Exception):
    """Raised when a single discovered_law call exceeds LAW_CALL_TIMEOUT_S."""


def _wrap_with_timeout(fn: Callable, timeout_s: float = LAW_CALL_TIMEOUT_S) -> Callable:
    """
    Wrap `fn` so any single call exceeding `timeout_s` raises _LawCallTimeout.
    Uses SIGALRM (Unix-only, main-thread-only). Falls back to the unwrapped
    function on Windows or off-main-thread, where SIGALRM is unavailable.
    """
    import signal
    import threading

    if not hasattr(signal, "SIGALRM"):
        return fn
    if threading.current_thread() is not threading.main_thread():
        return fn

    def _handler(signum, frame):
        raise _LawCallTimeout(f"discovered_law exceeded {timeout_s:g}s")

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            return fn(*args, **kwargs)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)

    return wrapper


def main():
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2,) * 2)
        # CPU is charged per request by the parent, not cumulatively per worker.
    namespace = None
    kind = None
    with open(os.devnull, "w") as discard:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                with (
                    contextlib.redirect_stdout(discard),
                    contextlib.redirect_stderr(discard),
                ):
                    if request["action"] == "compile":
                        if namespace is not None:
                            raise ValueError("worker already compiled")
                        namespace = {}
                        kind = request["kind"]
                        exec(  # noqa: S102 — isolated submitted-code execution
                            compile(
                                request["source"],
                                "<discovered_law>"
                                if kind == "law"
                                else "<fit_parameters>",
                                "exec",
                            ),
                            namespace,
                        )
                        if kind == "law":
                            if "discovered_law" not in namespace:
                                raise ValueError(
                                    "Source does not define a function named `discovered_law`"
                                )
                            namespace["discovered_law"] = _wrap_with_timeout(
                                namespace["discovered_law"]
                            )
                            result = {}
                        else:
                            result = {
                                "present": namespace.get("fit_parameters") is not None
                            }
                    elif namespace is None:
                        raise ValueError("worker is not compiled")
                    elif request["action"] == "call" and kind == "law":
                        result = namespace["discovered_law"](
                            *request.get("args", []), **request.get("kwargs", {})
                        )
                    elif request["action"] == "fit_parameters" and kind == "fit":
                        try:
                            result = {"spec": jsonable(namespace["fit_parameters"]())}
                        except Exception as exc:  # noqa: BLE001 — return submitted-code errors over the protocol
                            result = {"error": str(exc)}
                    else:
                        raise ValueError("invalid worker action")
                    response = {"ok": True, "result": jsonable(result)}
            except Exception as exc:  # noqa: BLE001 — return submitted-code errors over the protocol
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
