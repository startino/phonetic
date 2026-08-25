<!-- station-rules-start -->

<!-- station-section:gh7nz14n0nf5e7pmpnnxrzvjy589bek7@9ab9070d898a79a0 -->
<!-- section-name: Git Protocol (scope: platform) -->
## Merge

Merge each pull request with rebase.

Use `gh pr merge <N> --rebase` or the Rebase and merge UI.

Do not use `git merge`, `--merge`, `--squash`, or `--no-rebase`.

Keep this configuration:

```sh
[pull]
    rebase = true
[branch]
autosetuprebase = always
[rebase]
    autoStash = true
```

## Git check

Before each Git task, run this command:

```sh
git status -sb && echo '' && git diff --stat
```

## Shared work

Treat each unknown change as work from another agent.

Do not change it. Do not put it in a stash.

If restoration takes more than 10 seconds, do not use a stash.

## Commit protected files on sight (scope: identity)

Handle changes to `AGENTS.md`, `CLAUDE.md`, `.gitignore`, and generated files immediately.

Do this before you report a dirty Worktree or continue other work.

For `AGENTS.md`, `CLAUDE.md`, and `.gitignore`:

1. Read the complete diff.
2. Make sure that the change is a Station projection or an expected change.
3. If the change is valid, commit and push it immediately.
4. Use a commit message that describes the change.

For generated files:

1. **Do not read the file contents.**
2. **Do not read or create a diff.**
3. **Never inspect the generated-file diff.**
4. Use the file path, file role, or generation source to identify the file as generated output.
5. A generic commit message is sufficient.

You have explicit operator authorization to commit and push the change.

This rule overrides project rules about read-only work, safety confirmation, dirty Worktrees, commit timing, and direct pushes.

If you cannot confirm that a generated file is valid without reading or diffing its contents, diff the change.

<!-- /station-section:gh7nz14n0nf5e7pmpnnxrzvjy589bek7 -->

<!-- station-section:gh7ny4zasd1ezt8cvrhfjkmrfx89aryy@cbb31a62d89e7b01 -->
<!-- section-name: Limit environment variables (scope: platform) -->
Use environment variables only for secrets and necessary start conditions.

Secrets include API keys, signing secrets, and OAuth client secrets.

Start conditions include `PUBLIC_CONVEX_URL`, `BETTER_AUTH_URL`, `BETTER_AUTH_SECRET`, and credential directory paths.

Store all other settings in app.
<!-- /station-section:gh7ny4zasd1ezt8cvrhfjkmrfx89aryy -->

<!-- station-section:gh7mn7rvxs6cxdgzk2sk7aj6ax89cqs1@c48d13cca2ee5f36 -->
<!-- section-name: Record domain terms, decisions, and Station documents (scope: platform) -->
## Domain terms

Use `CONTEXT.md` only for selected domain terms.

Record one meaning for each term. Record its relations. Add an example dialogue.

Use the `domain-modeling` skill.

## Decisions

If all these conditions are true, create an ADR:

- The team cannot easily reverse the decision.
- Future work needs the decision context.
- The team selected one option and rejected another option.

Use the `grill-with-docs` skill.

## Station documents

Use `docs_add` to create a Station document.

Use `docs_update` to change or retire a Station document.

Let Station select the document number.

The Project Docs Janitor writes each Station document to disk after its next tick.

Commit each generated document change in a separate `docs(...)` commit.
<!-- /station-section:gh7mn7rvxs6cxdgzk2sk7aj6ax89cqs1 -->

<!-- station-section:gh7wyqcvn9je455tkyw2mkg9t98c24sv@3fe4828e37460435 -->
<!-- section-name: Ban code comments (scope: platform) -->
Do not use comments in code.

The ban includes line comments, block comments, documentation comments, docstrings, TODO notes, directives, notices, and commented-out code.

Delete each comment when you find it. Do not wait for a comment-removal task.

Do not move comment text to another comment or document.

Use names, types, interfaces, validation, errors, and module boundaries to show intent.

The codebase is the context. Make the codebase legible. Make the architecture communicate intent.

The work is complete only when the code contains no comments.
<!-- /station-section:gh7wyqcvn9je455tkyw2mkg9t98c24sv -->

<!-- station-section:gh7ra7r3vg7a28e87v357njvqh8c2gty@9cd590936360e86c -->
<!-- section-name: Write a test only at operator request (scope: platform) -->
Write a test only at the operator request.

Do not create, change, or remove a test without that request.

Design each test with the operator. Agree the scenario, the expected result, and the harmful regression that the test prevents.

Record each approved test in `docs/tests` in the same change as the test.

The approval record must name these five items:

1. The test file.
2. The approval date.
3. The harmful regression that the test prevents.
4. The scenario.
5. The expected result.

A test without a complete approval record is not approved. Remove it when you find it.
<!-- /station-section:gh7ra7r3vg7a28e87v357njvqh8c2gty -->

<!-- station-section:gh7q9p8bafyk0jsnn298e0keq58cyd6a@0ccaede6b9327e02 -->
<!-- section-name: Keep a skill to method, not to tool description (scope: platform) -->
A skill states why, when, and the approach.

A skill can mandate a tool, place the tool in the workflow, and instruct what to pass.

Write each of these as an action at a moment. Do not write it as a description of the tool.

Do not state the tool's capabilities. Do not state what the tool returns.

Do not restate what the tool already requires and rejects.

Do not restate a rule that already applies to every agent.

Do not add a rule against behavior that an agent does not do.

Reference a skill by its name. Do not reference a skill by a file path.

A path reaches one file. A skill reaches its complete method.

A file path belongs only inside the skill that owns the file.
<!-- /station-section:gh7q9p8bafyk0jsnn298e0keq58cyd6a -->

<!-- station-section:gh7gt76cchzghf2e241a58gqrh89bn02@bfc8a3693d982d61 -->
<!-- section-name: Keep release versions equal (scope: project) -->
The release version exists in these files:

- `pyproject.toml`, in `[project] version`
- `nix/package.nix`, in the `version` value for `pname = "phonetic"`

For each release, set both files to the same semantic version.

Commit both version changes together.

A change to `pyproject.toml` does not change `nix/package.nix`.

Different versions give the NixOS package an incorrect store-path version.
<!-- /station-section:gh7gt76cchzghf2e241a58gqrh89bn02 -->

<!-- station-section:gh7w8a9evbsv2c6qztr820v10s8cp9r8@64192eeafae7e635 -->
<!-- section-name: Know the phonetic architecture and modules (scope: project) -->
The `phonetic/` package holds the modules. They replace the older single `main.py` file.

The entry point is `phonetic.__main__:main`. The `[project.scripts]` table in `pyproject.toml` declares it.

`main.py` stays as a shim. It imports from `phonetic.__main__`.

The application has two modes. GUI mode uses a pystray tray icon and a customtkinter settings window. Headless mode starts with `--headless`, or when no display is available.

The threads have these functions:

- The main thread runs the customtkinter main loop.
- The tray runs in a daemon thread.
- The hotkeys use a Carbon event handler on macOS, and a pynput daemon thread on Linux and Windows.
- The transcription uses worker threads.

`App._msg_queue` is the message queue. In GUI mode, `root.after(100, ...)` reads it.

These modules have these functions:

- `config.py` gives the configuration for each platform. macOS uses `~/Library/Application Support/Phonetic`. Windows uses `%APPDATA%\Phonetic`. Linux uses `~/.config/phonetic`.
- `app.py` is the orchestrator. It sends the messages and holds the `toggle_recording` logic.
- `tray.py` holds the pystray `TrayManager`. It makes the icon in the program.
- `hotkeys.py` uses Carbon `RegisterEventHotKey` on macOS, pynput on Linux and Windows, and a `SIGUSR1` fallback on Linux.
- `ui/settings.py` holds the `CTkToplevel` settings window. This window is also the first-run wizard.
- `autostart.py` uses a LaunchAgent on macOS, the Registry on Windows, and an XDG `.desktop` file on Linux.

These dependencies are necessary:

- `quickmachotkey` on macOS only. It uses Carbon `RegisterEventHotKey` and needs no permission.
- `pynput` for the Linux and Windows hotkeys. It replaced python-xlib on Linux.
- `pystray` and `Pillow` for the tray icon.
- `customtkinter` for the settings interface.
- `pyobjc-framework-Cocoa` and `pyobjc-framework-ApplicationServices` on macOS only.
<!-- /station-section:gh7w8a9evbsv2c6qztr820v10s8cp9r8 -->

<!-- station-section:gh7x535segr1j534p8yrjf565x8cqgx9@2788881dca06bcb9 -->
<!-- section-name: Build phonetic in the Nix dev shell (scope: project) -->
Use the NixOS dev shell from `flake.nix`.

The shell must supply `linuxHeaders`. The `evdev` dependency of `pynput` needs them.

`C_INCLUDE_PATH` must contain the Linux headers. Without them, `evdev` does not compile.

The PyInstaller specification is at `packaging/phonetic.spec`.

The GitHub Actions release workflow is at `.github/workflows/release.yml`.

Use these commands for development:

- `uv run phonetic` starts GUI mode.
- `uv run phonetic --headless` starts headless mode, which the systemd service uses.
- `uv run phonetic --version` shows the version.
- `./service.sh` controls the systemd service. It calls `phonetic --headless`.
<!-- /station-section:gh7x535segr1j534p8yrjf565x8cqgx9 -->

<!-- station-section:gh7vvrt468nh4v8kezm9f6ek698cpnc1@eba871f65ed7df22 -->
<!-- section-name: Set each value correctly at its source (scope: project) -->
Set each value correctly where the code makes it.

Do not use a later layer to correct a wrong default. If a value must be X, set it to X at the source.

Do not add an override in the user interface or in glue code to correct a value.

An unnecessary override is not safe. If a person removes the override, the wrong behavior comes back without a signal.

Do not accept a behavior that is correct only because a different part of the system corrects it.
<!-- /station-section:gh7vvrt468nh4v8kezm9f6ek698cpnc1 -->

<!-- station-section:gh7jq56k2cmz3egqez38gftk8d8cp66b@6d6e41a29fe59a0b -->
<!-- section-name: Commit, verify, and release phonetic work (scope: project) -->
Commit and push after you complete the work.

Use a conventional commit prefix: `feat:`, `fix:`, `chore:`, or `docs:`.

Make each commit atomic. Put a new module, its integration, and the build configuration in separate commits.

Correct each warning, deprecation, and stale configuration that you find in tool output. Correct an old URL, a moved repository, a deprecation notice, and a lint warning as part of the current work. Do not leave it for later.

After you complete the work, verify it as fully as you can. Run the code. Examine the CI status. Test the imports. Make sure the configuration syntax is correct.

If the verification shows a failure, find the cause and correct it before you report that the task is complete.

After each update, push a semantic version tag to start the GitHub Actions release workflow:

```sh
git tag vX.Y.Z && git push origin vX.Y.Z
```

After you push, make sure that GitHub Actions completed correctly. Use `gh run list --limit 1` and `gh run view`. If a run fails, find the cause and correct it before you report that the task is complete.

Do not ask the operator to approve a routine decision. Do the work, verify it, and report the result.
<!-- /station-section:gh7jq56k2cmz3egqez38gftk8d8cp66b -->

<!-- station-section:gh7k7jsam0gdr52tdbxzzgvh5d8cqrwm@e8f97cb4e6be889c -->
<!-- section-name: Instrument phonetic before you correct it (scope: project) -->
Add instrumentation first. Correct the code second.

Do not guess the cause. Add logging or diagnostics to show exactly where the pipeline fails before you change any logic.

For an audio or binary pipeline, write the intermediate output to a file in `/tmp`, for example `/tmp/phonetic_debug.wav`. Then you can examine that output separately.

When data moves through more than one stage, record the shape, the size, and the important properties at each boundary. This shows where the data becomes incorrect.

After you apply a correction, run the code and make sure that the output changed.

Keep each `log()` call in the codebase permanently. Add as many as you can.

Do not remove a log call. In a bundled application build, stderr is not visible, so the logs are the only diagnostic source.
<!-- /station-section:gh7k7jsam0gdr52tdbxzzgvh5d8cqrwm -->

<!-- station-section:gh7k0cf2nf9kcykjkkqyr1xrh58cq437@32d48fbc680c7223 -->
<!-- section-name: Clean macOS fully before each install test (scope: project) -->
Do a full clean before each install test. Do not do a partial reinstall.

The operator wants proof that the complete install flow operates from the start each time.

Run this clean procedure first:

```bash
# FIRST: detach all DMG volumes (stale mounts cause wrong binary installs)
hdiutil detach /Volumes/Phonetic 2>/dev/null; hdiutil detach "/Volumes/Phonetic 1" 2>/dev/null; hdiutil detach "/Volumes/Phonetic 2" 2>/dev/null; hdiutil detach "/Volumes/Phonetic 3" 2>/dev/null
pkill -9 -f "phonetic" 2>/dev/null; pkill -9 -f "Phonetic" 2>/dev/null
rm -rf ~/Applications/Phonetic.app /Applications/Phonetic.app
rm -rf ~/"Library/Application Support/Phonetic" ~/.config/phonetic
rm -f ~/Library/Preferences/no.starti.phonetic.plist ~/Library/Preferences/com.startino.phonetic.plist
rm -f ~/Library/LaunchAgents/no.starti.phonetic.plist ~/Library/LaunchAgents/com.startino.phonetic.plist
find ~/"Library/Application Support/CrashReporter" -name "phonetic_*" -delete 2>/dev/null
find ~/Library/Logs/DiagnosticReports -name "phonetic-*" -delete 2>/dev/null
rm -f /tmp/phonetic_startup.log /tmp/phonetic_debug.wav
rm -f ~/Downloads/Phonetic.dmg ~/Downloads/Phonetic.zip 2>/dev/null
defaults delete com.apple.dock recent-apps 2>/dev/null; killall Dock 2>/dev/null
tccutil reset Microphone no.starti.phonetic 2>/dev/null; tccutil reset Accessibility no.starti.phonetic 2>/dev/null
tccutil reset Microphone com.startino.phonetic 2>/dev/null; tccutil reset Accessibility com.startino.phonetic 2>/dev/null

# Purge LaunchServices ghost entries (old DMG/dev builds show as duplicate apps in Launchpad/Spotlight)
LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
"$LSREG" -u /Applications/Phonetic.app 2>/dev/null
"$LSREG" -u ~/Applications/Phonetic.app 2>/dev/null
"$LSREG" -u /Volumes/Phonetic/Phonetic.app 2>/dev/null
"$LSREG" -u "/Volumes/Phonetic 1/Phonetic.app" 2>/dev/null
"$LSREG" -u "/Volumes/Phonetic 2/Phonetic.app" 2>/dev/null
"$LSREG" -u "/Volumes/Phonetic 3/Phonetic.app" 2>/dev/null
"$LSREG" -u ~/vcs/startino/phonetic/dist/Phonetic.app 2>/dev/null
# Reset Launchpad to remove ghost icons
defaults write com.apple.dock ResetLaunchPad -bool true; killall Dock 2>/dev/null

# Verify — nothing should remain outside source repo, uv cache, and claude dirs
find ~ /tmp -name "*phonetic*" -o -name "*Phonetic*" 2>/dev/null | grep -v "/vcs/" | grep -v "/.cache/uv/" | grep -v "/.claude/" | grep -v "/claude-cli-nodejs/"
# Verify — only one (or zero) in Applications dirs
find ~/Applications /Applications -maxdepth 1 -name "*Phonetic*" 2>/dev/null
```

Then install from the release:

```bash
gh release download vX.Y.Z --pattern "Phonetic.dmg" --dir ~/Downloads
hdiutil attach ~/Downloads/Phonetic.dmg -nobrowse
mkdir -p ~/Applications
cp -R "/Volumes/Phonetic/Phonetic.app" ~/Applications/
xattr -cr ~/Applications/Phonetic.app
hdiutil detach /Volumes/Phonetic
# Re-register in LaunchServices so Spotlight/Launchpad find it
LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
"$LSREG" -f ~/Applications/Phonetic.app
open ~/Applications/Phonetic.app
```
<!-- /station-section:gh7k0cf2nf9kcykjkkqyr1xrh58cq437 -->

<!-- station-section:gh7r0ts64a4951pnw2ncgfq5k98cq9aj@103ba9a1216f2d0a -->
<!-- section-name: Obey the macOS install rules (scope: project) -->
Always install to `~/Applications/`. Never install to `/Applications/`.

On Sequoia, `/Applications/` has the `com.apple.provenance` extended attribute. That attribute stops an unsigned dylib.

When you open a DMG, Finder can copy the application to `/Applications/` with a drag. After each install, examine both locations.

After the clean procedure, make sure that only one copy is present:

```sh
find ~/Applications /Applications -maxdepth 1 -name "*Phonetic*"
```

A DMG stays attached at `/Volumes/Phonetic` after the install. Always detach it before you install again.

macOS keeps a LaunchServices record when you open `Phonetic.app` from a DMG, from `/Applications/`, or from `dist/`. The record stays after you delete the application, and Launchpad and Spotlight then show a second Phonetic.

To remove the record, use `lsregister -u <stale-path>`. Then run:

```sh
defaults write com.apple.dock ResetLaunchPad -bool true; killall Dock
```

The clean procedure does this.

A build before approximately v0.5.20 used the bundle identifier `com.startino.phonetic`. The current identifier is `no.starti.phonetic`. Remove both identifiers from TCC, from the preferences, and from LaunchServices.
<!-- /station-section:gh7r0ts64a4951pnw2ncgfq5k98cq9aj -->

<!-- station-section:gh7p9gr0j04wwhz4v09pyknwq98cqhc2@a10e11dcde59e473 -->
<!-- section-name: Know the macOS platform limits (scope: project) -->
The bundle identifier is `no.starti.phonetic`.

Sequoia sets an immutable `com.apple.provenance` extended attribute on an application in `/Applications`. It stops an unsigned dylib. Install to `~/Applications` instead.

macOS translocates an application that starts from a DMG to a temporary path. dyld also stops that application. Copy the application out of the DMG first.

A background application with `LSUIElement` cannot show a system permission dialog. Set `NSApplicationActivationPolicyRegular` and call `activateIgnoringOtherApps_` before you request a permission.

Start `tk.Tk()` before you call `NSApplication.setActivationPolicy_`. In the other sequence, Tk stops with an unrecognized selector fault for `GetRGBA`.

`requestAccessForMediaType_completionHandler_` fails with "Argument 3 is a block, but no signature available". Call `objc.registerMetaDataForSelector` to register the block type before you call the method.

An open `sounddevice` `InputStream` does not start the macOS microphone permission dialog for a bundled application. Use the AVFoundation API directly.

On macOS Sequoia, a `keyboard.Listener` or `GlobalHotKeys` object that starts from a background thread stops with `dispatch_assert_queue_fail` in `TSMGetInputSourceProperty`. Make each listener one time at startup. Do not stop a listener and make it again.

On macOS, the Option key changes the character. As an example, Alt and R together give the character `®`. `GlobalHotKeys` from pynput cannot match that character. Match on the virtual key code instead.

On macOS, `event.keycode` from tkinter holds the virtual key code in bits 24 to 31. Read it with `(event.keycode >> 24) & 0xFF`.

pynput uses `CGEventTap`, which needs the Input Monitoring permission and not the Accessibility permission. An application with an ad-hoc signature cannot request that permission in the program, and it does not appear in System Settings for the user.

Carbon `RegisterEventHotKey` needs no permission. Version v0.5.55 replaced pynput with quickmachotkey, which uses Carbon HIToolbox, on macOS. The API is deprecated, but it is the only method that needs no permission. Version v0.5.57 operated correctly on Tahoe 26.3.
<!-- /station-section:gh7p9gr0j04wwhz4v09pyknwq98cqhc2 -->

<!-- station-rules-end -->
