"""Microphone permission — the macOS TCC grant, as a UI-free core function.

`phonetic grant-mic` invokes ``grant_microphone()``. This is the first-run macOS
mic-permission grant, lifted OUT of the App (where it was ``_check_mic_permission``
+ ``_show_mic_denied_dialog``, both tkinter-coupled) into the core so it is
reachable headlessly — the daemon and the CLI both need it, and neither should
have to import the UI to ask for the mic.

macOS landmines reproduced faithfully (CLAUDE.md):
- AVFoundation ``AVCaptureDevice`` authorization + request.
- The foreground moment: ``NSApplication setActivationPolicy_(Regular)`` +
  ``activateIgnoringOtherApps_`` — TCC needs the app's own bundle identity AND a
  foreground app for the dialog to appear.
- PyObjC block-signature registration via ``objc.registerMetaDataForSelector``
  for ``requestAccessForMediaType:completionHandler:`` (without it PyObjC can't
  call the completion block).
- Reporting is print/log ONLY — never ``tkinter.messagebox`` — so the function
  is genuinely headless and never inits Tk. The headless path must NOT init Tk
  at all ("tkinter must init before AppKit or Tk crashes"); this function simply
  never touches Tk, sidestepping the ordering hazard entirely.

Non-macOS: a clean no-op with a correct exit signal — there is no TCC mic grant
to perform, and nothing here imports any UI.
"""

import sys
import threading

from .log import log


def microphone_status() -> str:
    """Return the macOS mic authorization as one of: 'authorized', 'denied',
    'restricted', 'not_determined', 'unavailable', or 'not_applicable'.

    Read-only: queries AVFoundation without triggering the request dialog. On
    non-macOS returns 'not_applicable'. Used by ``phonetic doctor`` and as the
    pre-check inside ``grant_microphone``.
    """
    if sys.platform != "darwin":
        return "not_applicable"
    try:
        import objc
        objc.loadBundle(
            "AVFoundation", {},
            bundle_path="/System/Library/Frameworks/AVFoundation.framework",
        )
        AVCaptureDevice = objc.lookUpClass("AVCaptureDevice")
        status = AVCaptureDevice.authorizationStatusForMediaType_("soun")
        return {
            0: "not_determined",
            1: "restricted",
            2: "denied",
            3: "authorized",
        }.get(status, "unavailable")
    except Exception as exc:
        log(f"mic_permission: status query failed: {exc}")
        return "unavailable"


def grant_microphone() -> bool:
    """Ensure macOS microphone access, triggering the TCC dialog if undetermined.

    Returns True if access is (or becomes) authorized, False otherwise. On
    non-macOS this is a no-op that returns True (nothing to grant). All reporting
    is print/log; no UI is imported and Tk is never initialized.
    """
    if sys.platform != "darwin":
        print("grant-mic: no microphone permission step is needed on this "
              "platform (macOS only). Nothing to do.")
        log("mic_permission: grant_microphone no-op on non-macOS")
        return True

    log("mic_permission: grant_microphone starting")
    try:
        import objc
        log("mic_permission: loading AVFoundation")
        objc.loadBundle(
            "AVFoundation", {},
            bundle_path="/System/Library/Frameworks/AVFoundation.framework",
        )

        # Register the completion-handler block signature so PyObjC can call it.
        objc.registerMetaDataForSelector(
            b"AVCaptureDevice",
            b"requestAccessForMediaType:completionHandler:",
            {
                "arguments": {
                    3: {
                        "callable": {
                            "retval": {"type": b"v"},
                            "arguments": {
                                0: {"type": b"^v"},
                                1: {"type": b"Z"},
                            },
                        }
                    }
                }
            },
        )

        AVCaptureDevice = objc.lookUpClass("AVCaptureDevice")
        status = AVCaptureDevice.authorizationStatusForMediaType_("soun")
        log(f"mic_permission: status = {status} "
            f"(0=notDetermined, 1=restricted, 2=denied, 3=authorized)")

        if status == 3:  # Authorized
            print("Microphone access is already authorized.")
            return True

        if status == 0:  # Not determined — trigger the system dialog
            log("mic_permission: not determined, becoming foreground app")
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyRegular,
            )
            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            app.activateIgnoringOtherApps_(True)

            log("mic_permission: requesting access via AVCaptureDevice")
            print("Requesting microphone access -- approve the system dialog...")
            event = threading.Event()
            granted_box: list[bool] = [False]

            def _handler(granted: bool) -> None:
                log(f"mic_permission: handler called, granted={granted}")
                granted_box[0] = granted
                event.set()

            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                "soun", _handler,
            )
            log("mic_permission: waiting for user response")
            event.wait(timeout=120)
            log(f"mic_permission: result = {granted_box[0]}")
            if granted_box[0]:
                print("Microphone access granted.")
                return True
            print(_DENIED_MESSAGE, file=sys.stderr)
            return False

        # Denied (2) or Restricted (1)
        log("mic_permission: denied/restricted")
        print(_DENIED_MESSAGE, file=sys.stderr)
        return False
    except Exception as exc:
        log(f"mic_permission: EXCEPTION: {exc}")
        print(f"grant-mic: could not complete the microphone permission "
              f"request: {exc}", file=sys.stderr)
        return False


_DENIED_MESSAGE = (
    "Microphone access is not granted. Phonetic needs it to record audio.\n"
    "  1. Open System Settings -> Privacy & Security -> Microphone\n"
    "  2. Find Phonetic and toggle it ON\n"
    "  3. Run `phonetic grant-mic` again (or just start Phonetic)."
)
