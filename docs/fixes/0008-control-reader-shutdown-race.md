# Control FIFO reader thread raises TypeError on shutdown

**Date:** 2026-06-04
**Symptom:** On daemon shutdown, the control-channel reader thread prints
`TypeError: 'NoneType' object cannot be interpreted as an integer` from
`os.read(self._fd, 4096)`. Harmless (daemon thread, no functional impact) but
noisy — surfaced loudly when the areliant daemon-init test starts and stops the
control channel in-process.
**Affected:** `phonetic/control.py:79` (`ControlChannel._reader_loop`)
**Root cause:** The reader loop read `self._fd` multiple times per iteration
(the `while` guard, `select.select([self._fd], ...)`, and `os.read(self._fd, ...)`).
`stop()` runs on another thread and sets `self._fd = None` after closing the fd.
Between the loop's guard check and the `os.read`, `stop()` could null `self._fd`,
so `os.read(None, 4096)` raised `TypeError` — which is NOT in the loop's
`except (OSError, ValueError)` handler, so it escaped to the thread's top level.

## Investigation
1. The areliant test (`tests/test_areliant.py::test_daemon_starts_with_ui_blocked`)
   calls `App.start()` then `App._shutdown()` in-process. With the control reader
   actually running and then stopped, the race fired every run, printing the
   TypeError to stderr during the test.
2. Confirmed the read-after-null window: `_reader_loop` referenced `self._fd`
   (not a local snapshot), so `stop()` nulling it mid-iteration left `os.read`
   with `None`. `TypeError` is unhandled by the loop's `except (OSError, ValueError)`.
3. Dead end considered: widening the `except` to swallow `TypeError`. Rejected —
   that hides the real defect (reading a shared mutable fd without a snapshot)
   and would mask genuine type bugs.

## Fix
`_reader_loop` now snapshots `self._fd` into a local `fd` ONCE at the top of each
iteration and breaks if it is `None`; all of `select`/`os.read` use the local
`fd`. A concurrent `stop()` nulling `self._fd` can no longer turn into
`os.read(None)` — the next iteration simply sees `fd is None` and exits cleanly.

**Commit:** see `fix(control):` commit on `worktree-feat+areliant-cli-core`.
