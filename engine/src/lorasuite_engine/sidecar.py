from __future__ import annotations

import argparse
import errno
import os
import sys
import threading
import time
from collections.abc import Callable, Sequence

import uvicorn

from lorasuite_engine.api import create_app


def _process_is_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_alive(process_id)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        if error.errno == errno.EPERM:
            return True
        raise
    return True


def _windows_process_is_alive(process_id: int) -> bool:
    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        return ctypes.get_last_error() == 5
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def _watch_parent(
    parent_process_id: int,
    *,
    poll_interval_seconds: float = 1.0,
    process_is_alive: Callable[[int], bool] = _process_is_alive,
    exit_process: Callable[[int], object] = os._exit,
) -> None:
    while process_is_alive(parent_process_id):
        time.sleep(poll_interval_seconds)
    exit_process(0)


def _start_parent_watchdog(parent_process_id: int) -> None:
    thread = threading.Thread(
        target=_watch_parent,
        args=(parent_process_id,),
        name="lorasuite-parent-watchdog",
        daemon=True,
    )
    thread.start()


def _watch_packaged_launcher(
    launcher_pid: int,
    *,
    parent_pid: Callable[[], int] = os.getppid,
    exit_process: Callable[[int], object] = os._exit,
) -> None:
    # A one-file bootloader and its Python worker are different processes.
    # SIGKILL cannot be forwarded by the bootloader. Watch the actual parent
    # relationship too, so an orphaned worker closes downstream lifeline pipes.
    while launcher_pid > 1 and parent_pid() == launcher_pid:
        time.sleep(0.5)
    exit_process(0)


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LoraSuite desktop engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(arguments)
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("the desktop engine may only bind to localhost")
    if args.port < 1024 or args.port > 65_535:
        parser.error("port must be between 1024 and 65535")
    if args.parent_pid is not None and args.parent_pid <= 0:
        parser.error("parent pid must be a positive integer")
    return args


def main() -> None:
    args = _parse_args()
    if getattr(sys, 'frozen', False) and os.name != 'nt':
        threading.Thread(target=_watch_packaged_launcher, args=(os.getppid(),),
                         name='lorasuite-launcher-watchdog', daemon=True).start()
    if args.parent_pid is not None:
        _start_parent_watchdog(args.parent_pid)
    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
        workers=1,
    )


if __name__ == "__main__":
    main()
