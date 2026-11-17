# Maestro flow reference for testkit

Checked against Maestro CLI 2.12.0 (`maestro check-syntax` accepts every snippet here). Full docs: https://docs.maestro.dev.

## File shape

```yaml
appId: ${MAESTRO_APP_ID}          # header: appId (native) or url (web); env vars are interpolated
name: TC-S1-004 Reset password from the login screen
tags: [PROJ-123, S1, P1]
env:                               # defaults for flow variables; MAESTRO_* vars come from the shell
  NEW_NAME: ${NEW_NAME || "QA Tester"}
onFlowStart:
  - runFlow: _shared/dismiss-onboarding.yaml
---
- launchApp
```

Do not name a flow `config.yaml`: Maestro treats that file in the workspace folder as workspace config.

## Commands used most

| Need | Command |
|---|---|
| Start fresh | `- launchApp: {clearState: true, clearKeychain: true}` (keychain: iOS) |
| Start keeping login | `- launchApp: {stopApp: true}` |
| Stop / kill | `- stopApp` · `- killApp` |
| Tap by text / id / index | `- tapOn: "Sign in"` · `- tapOn: {id: "submit_btn"}` · `- tapOn: {text: "Delete", index: 1}` |
| Tap relative | `- tapOn: {text: "Edit", below: "Shipping address"}` |
| Long press / double tap | `- longPressOn: "Item 1"` · `- doubleTapOn: "Photo"` |
| Type | `- inputText: ${MAESTRO_MEMBER_EMAIL}` · random data: `- inputRandomEmail`, `- inputRandomText`, `- inputRandomNumber` |
| Clear a field | `- eraseText: 50` |
| Keyboard | `- hideKeyboard` · `- pressKey: Enter` · `- pressKey: back` (Android back) |
| Scroll | `- scroll` · `- scrollUntilVisible: {element: {text: "Terms"}, direction: DOWN, timeout: 20000}` |
| Swipe | `- swipe: {direction: LEFT}` · `- swipe: {start: "90%,50%", end: "10%,50%"}` |
| Wait | `- extendedWaitUntil: {visible: "Welcome", timeout: 10000}` · `notVisible:` · `- waitForAnimationToEnd` |
| Assert | `- assertVisible: "Order #42"` · `- assertNotVisible: "Error"` · `- assertVisible: {id: "cart_badge", text: "2"}` · `- assertTrue: ${output.total == "120.00"}` |
| Copy text | `- copyTextFrom: {id: "order_number"}` then `- inputText: ${maestro.copiedText}` |
| Evidence | `- takeScreenshot: TC-S1-004-step3` · video: `- startRecording: TC-S1-004` … `- stopRecording` |
| Back / home | `- back` (Android) · `- pressKey: home` |
| Deep link | `- openLink: myapp://orders/42` · universal link: `- openLink: {link: "https://example.com/o/42", autoVerify: true}` (Android: auto-accept the "Open with" chooser) |
| Browser link without app | `- openLink: {link: "https://…", browser: true}` |
| Location | `- setLocation: {latitude: 10.7769, longitude: 106.7009}` |
| Airplane mode (Android) | `- setAirplaneMode: enabled` · `- toggleAirplaneMode` |
| Clipboard / media | `- setClipboard: "text"` · `- addMedia: [ "./assets/photo.jpg" ]` |
| Sub-flow | `- runFlow: {file: _shared/login.yaml, env: {EMAIL: "${MAESTRO_ADMIN_EMAIL}"}}` |
| Condition | `- runFlow: {when: {visible: "Allow"}, commands: [ {tapOn: "Allow"} ]}` · `when: {platform: iOS}` |
| Retry flaky step | `- retry: {maxRetries: 2, commands: [ {tapOn: "Refresh"}, {assertVisible: "Updated"} ]}` |
| Repeat | `- repeat: {times: 3, commands: [ {tapOn: "+"} ]}` |
| JavaScript | `- evalScript: ${output.total = Number(maestro.copiedText.replace(/[^0-9.]/g, ""))}` · `- runScript: _shared/make-order.js` (can call HTTP APIs with `http.post`) |

## Permissions

```yaml
- launchApp:
    clearState: true
    permissions:
      all: deny               # start from a known state
      camera: allow
      location: allow         # android/ios names: camera, location, notifications, photos, contacts, microphone, …
```

- Permission prompts that still appear (Android 13+ notifications, iOS ATT, in-app pre-prompts): handle with a conditional `runFlow` on the dialog text and **assert the app's behaviour after deny** as its own case.
- Test the deny path explicitly (`permissions: {camera: deny}` then the screen that needs the camera shows the documented fallback).

## Deep links

- Custom scheme from `mobile.deep_link_scheme`: `- openLink: ${MAESTRO_DEEP_LINK_SCHEME}://orders/42`.
- Cold vs warm start are different cases: `- stopApp` before `openLink` for cold start; logged-out deep link should go through login and land on the target.
- From the shell (debugging): Android `adb shell am start -W -a android.intent.action.VIEW -d "myapp://orders/42" <app_id>`; iOS `xcrun simctl openurl booted "myapp://orders/42"`.

## Platform differences

- iOS text fields: tap the field before `inputText`; `hideKeyboard` may need a tap outside on some keyboards (`- tapOn: {point: "50%,10%"}`).
- Android `back` has no iOS equivalent; use `when: {platform: Android}`.
- Ids: Android `resource-id` is `com.example.app:id/password_input` or `password_input`; iOS uses `accessibilityIdentifier`. Ask developers for ids on controls without stable text (icons).
- Find selectors with `maestro hierarchy` (prints the current UI tree) or `maestro studio` (interactive, opens a local web UI).

## Running directly (outside the wrapper)

```bash
maestro --device <id> test qa/runs/R/mobile/S1/TC-S1-001.yaml \
  --format junit --output qa/runs/R/results/S1-maestro.xml --test-output-dir qa/runs/R/evidence/S1/maestro
```

- `--output` must point into an existing folder (Maestro does not create it).
- `--test-output-dir` gets `<timestamp>/<flow name>/` with `commands.json`, `logs/maestro.log`, `takeScreenshot/*.png`, and on failure `screenshots/step-NNN-*.png` plus `screen-hierarchy/*.json`. Do not combine with `--flatten-debug-output`: in 2.12.0 that drops the `takeScreenshot` files.
- JUnit: one `<testcase name="<flow name>" file="<path>" status="SUCCESS|ERROR">` per flow, with `<failure>` text on failure and the `device` attribute on `<testsuite>`.
- `--include-tags P0` / `--exclude-tags slow` filter flows by `tags`.
- `-p web --headless` runs flows with `url:` headers in Chromium (Maestro web support, beta); testkit uses the `browser-testing` skill for web instead.
