---
name: mobile-testing
description: How testkit tests native and hybrid mobile apps (Android, iOS) with Maestro — writing one YAML flow per test case under qa/runs/<RUN_ID>/mobile/<STREAM_ID>/, checking syntax, installing and launching the app on an emulator, simulator or real device, test accounts through MAESTRO_* environment variables, deep links, permission dialogs, screenshots as evidence, JUnit results turned into PASS/FAIL rows, and the WebView part of hybrid apps. Use when cases have `Type: mobile`, when the user says "test the app", "mobile app", "Android", "iOS", "Maestro", "emulator", "simulator", "kiểm thử ứng dụng di động", "test app điện thoại", or when qa/config.yml has a `mobile:` block.
argument-hint: "<RUN_ID> <STREAM_ID> [--device <id>] [--platform android|ios]"
---

# Mobile testing with Maestro

[Maestro](https://maestro.mobile.dev) drives the app through the OS accessibility layer, so one YAML flow works on Android and iOS, waits for the UI by itself and needs no app changes. testkit uses it the way it uses the browser: one stream at a time per device, evidence screenshots, the same case IDs and statuses.

```bash
SK=$(ls -d .claude/skills .agents/skills 2>/dev/null | head -1)   # the skills folder testkit installed into
MR=$SK/mobile-testing/scripts/maestro_run.sh
```

## 1. Configuration (`qa/config.yml`)

```yaml
mobile:
  tool: maestro                      # maestro (default) | appium (see section 8)
  platforms: [android, ios]          # what the product ships; cases say which they cover
  app_id:
    android: com.example.app         # applicationId
    ios: com.example.app             # bundle identifier
  build:                             # where the executor gets the build under test; one per platform
    android: builds/app-staging.apk  # path, or url_env: TESTKIT_APK_URL, or store: "Play internal testing"
    ios: builds/App-staging.app      # simulator .app (zip ok); real devices need a signed .ipa / TestFlight
  device:
    android: emulator-5554           # adb serial, AVD name, or "any"
    ios: "iPhone 16"                 # simulator name or UDID, or "any"
  deep_link_scheme: myapp            # custom scheme the app registers (optional)
  environment: staging               # which qa/config.yml environment the build talks to
  allow_write: true                  # same meaning as for web environments
```

Builds come from the team (CI artifact, internal store). Never point a test build at production unless the environment entry says so, and never use real customer accounts.

## 2. How the script-writer marks mobile cases

Mobile cases follow the `test-case-standard` skill with two extra fields:

```markdown
### TC-S1-001 — Log in with a valid email and password
- Priority: P0
- Type: mobile
- Platform: android, ios            # or one of them; "web" parts of a hybrid flow say so per step
- Requirement: AC-1
- Preconditions: App installed fresh (clear state). Notifications permission: deny.
- Test data: account `{{member}}`
- Steps:
  1. Launch the app.
  2. Tap "Email", type `{{member.email}}`; tap the password field, type `{{member.password}}`.
  3. Tap "Sign in".
- Expected:
  - Home screen shows "Welcome, <display name>" within 10 s.
```

Steps name the visible text or accessibility id of each control (as on screen, not code names), and state permission answers and app state (fresh install, logged in, offline) as preconditions. The writer explores the app with `maestro studio` or `maestro hierarchy` when a device is available, and records `Platform`.

## 3. Writing flows

One flow file per case: `qa/runs/<RUN_ID>/mobile/<STREAM_ID>/<TC_ID>.yaml`; shared steps in `.../<STREAM_ID>/_shared/*.yaml` (called with `runFlow`, never run alone). Start from `assets/example-flow.yaml` (and `assets/login-subflow.yaml`).

```yaml
appId: ${MAESTRO_APP_ID}
name: TC-S1-001 Log in with a valid email and password     # name starts with the TC ID
tags: [PROJ-123, S1, P0]
---
- launchApp:
    clearState: true
    permissions: {notifications: deny}
- tapOn: "Email"
- inputText: ${MAESTRO_MEMBER_EMAIL}
- tapOn: {id: "password_input"}
- inputText: ${MAESTRO_MEMBER_PASSWORD}
- tapOn: "Sign in"
- extendedWaitUntil: {visible: "Welcome", timeout: 10000}
- takeScreenshot: TC-S1-001-step3                          # evidence name = <TC_ID>-step<N>
```

- Every expected result becomes an assertion (`assertVisible`, `assertNotVisible`, `assertTrue`, `extendedWaitUntil`) followed by `takeScreenshot: <TC_ID>-step<N>`.
- Selectors: visible text first, then `id` (Android resource-id / iOS accessibilityIdentifier), then relative (`below:`, `childOf:`). Coordinates only as a last resort, as percentages (`point: "50%,90%"`).
- Command reference, deep links, permissions, keyboard, scrolling, conditions, JavaScript and platform differences: `references/maestro-flows.md`.
- Validate before running: `$MR <RUN_ID> <STREAM_ID> --check-only` (runs `maestro check-syntax` on every flow; no device needed).

## 4. Test accounts and secrets

Maestro reads every environment variable that starts with `MAESTRO_` automatically. The executor creates accounts as the `test-executor` agent describes (`qa/accounts.local.json`) and exports them for the run:

```bash
export MAESTRO_APP_ID=com.example.app
export MAESTRO_MEMBER_EMAIL='qa+proj-123-s1-member-1731810000@example.test'
export MAESTRO_MEMBER_PASSWORD='<from qa/accounts.local.json>'     # typed by you from the file, never echoed
```

Never pass secrets with `-e KEY=value` (visible in the process list) and never write them into flows. Maestro logs typed text in clear in `commands.json` and `maestro.log`; `maestro_run.sh` redacts the values of all `MAESTRO_*` variables from the run's artifacts afterwards. Do not attach artifacts from a run that bypassed the wrapper.

## 5. Device and app setup

Read `references/device-setup.md` for Android emulators (`avdmanager`, `emulator`, `adb install`), iOS simulators (`xcrun simctl boot/install`), real devices, and installing the build. In short:

1. `maestro list-devices` (or `adb devices`, `xcrun simctl list devices booted`): pick the device from `mobile.device`; one stream per device, never two streams on one device.
2. Install the build under test (`adb install -r <apk>` / `xcrun simctl install booted <App.app>`), note its version for the results header (`adb shell dumpsys package <id> | grep versionName`, or the app's About screen).
3. Permissions: grant/deny in `launchApp.permissions`; handle what still pops up with a conditional `runFlow`.

No device and no way to start one (no Android SDK/Xcode): stop, mark the stream's cases `BLOCKED` with "no mobile device available", and tell the lead. Do not guess results.

## 6. Running a stream

```bash
$MR PROJ-123 S1 --device emulator-5554          # or --device <iOS UDID>; --platform android|ios
```

The wrapper: checks Java 17+ and Maestro, runs `check-syntax` on every flow, then
`maestro test <flows> --format junit --output qa/runs/<RUN_ID>/results/<S>-maestro.xml --test-output-dir qa/runs/<RUN_ID>/evidence/<S>/maestro`, then `scripts/maestro_report.py` which redacts secrets, copies screenshots to `qa/runs/<RUN_ID>/evidence/<S>/<name>.png` (failure screenshot → `<TC_ID>-fail.png`) and prints result rows:

```
| Case | Status | Evidence | Notes |
| TC-S1-001 | PASS | qa/runs/PROJ-123/evidence/S1/TC-S1-001-step3.png | |
| TC-S1-002 | FAIL | qa/runs/PROJ-123/evidence/S1/TC-S1-002-fail.png | Assertion is false: "Order #42" is visible |
```

Exit 0 = all passed, 1 = a flow failed, 2 = setup problem. Then, exactly as for browser cases (`test-executor` agent):

- Open every screenshot you report; a PASS whose screenshot shows an error dialog is not a pass.
- A failing flow: rerun that one case from a clean state with `$MR <RUN_ID> <STREAM_ID> --only <TC_ID>` (writes `results/<S>-<TC_ID>-maestro.xml`, keeps the stream report). Distinguish a product bug from a flow bug (wrong selector, timing): fix the flow and rerun; only a real behaviour difference becomes a bug (`bug-reporting` skill). Put device, OS version and app version in the bug's `browser`/environment fields, e.g. `browser: maestro 2.12.0, Pixel 8 API 35 emulator, app 3.4.1 (412)`.
- Copy the rows into `qa/runs/<RUN_ID>/results/<STREAM_ID>.md` with priorities and bug links; mark cases whose `Platform` you could not run `BLOCKED` with the reason.

## 7. Hybrid apps (WebView)

Maestro sees WebView content through accessibility, so `tapOn: "text"` usually works inside a WebView too. When the web part needs more (console errors, network, DOM checks, long forms):

- Test the same web pages with the `browser-testing` skill at the mobile viewport (the WebView loads a URL of a configured environment; find it in the app config or `adb logcat`), and keep Maestro for the native shell: launch, login handoff, deep links, permissions, back button, push.
- Android debug builds with `WebView.setWebContentsDebuggingEnabled(true)`: `adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>` exposes the WebView over CDP for inspection. Use it only for reading state and evidence, the flow still runs in Maestro.
- Mark such steps in the case: `Platform: android (native) + web (WebView)`.

## 8. Alternatives

Appium (WebDriver protocol, needs an Appium server plus UiAutomator2/XCUITest drivers) fits when the team already has an Appium suite or needs things Maestro cannot do (multi-app flows with fine control, low-level gestures). testkit does not wrap it; if `mobile.tool: appium`, follow the team's existing suite and keep the same output layout and statuses. Maestro Cloud (`maestro cloud`) is a paid service: ask the user before uploading builds.

## 9. Tools

| Tool | Required | Install |
|---|---|---|
| Java 17+ | yes | macOS `brew install openjdk@21` · Linux `apt install openjdk-17-jdk` · Windows `winget install EclipseAdoptium.Temurin.21.JDK` |
| Maestro CLI 2.12.x | yes | macOS/Linux `export MAESTRO_VERSION=2.12.0; curl -fsSL https://get.maestro.mobile.dev \| bash` or `brew tap mobile-dev-inc/tap && brew install mobile-dev-inc/tap/maestro` · Windows: unzip `maestro.zip` from the GitHub release `cli-2.12.0`, add `maestro\bin` to PATH (or use WSL) |
| Android SDK platform-tools + emulator | for Android | Android Studio, or `brew install --cask android-commandlinetools` · `winget install Google.AndroidStudio` |
| Xcode + iOS simulators | for iOS (macOS only) | App Store |

Maestro sends anonymous analytics unless `MAESTRO_CLI_NO_ANALYTICS=1`; the wrapper sets it.
