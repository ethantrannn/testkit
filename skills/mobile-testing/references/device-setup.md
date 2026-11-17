# Devices and builds

testkit never installs the Android SDK or Xcode for the user; it uses what is there and says what is missing. One stream per device at a time.

## Pick a device

```bash
maestro list-devices                      # Android emulators/AVDs, iOS simulators, web
adb devices -l                            # connected Android devices and running emulators
xcrun simctl list devices booted          # running iOS simulators (macOS)
```

Use `mobile.device.<platform>` from `qa/config.yml`; `any` means the first available. Pass the id to the wrapper: `--device emulator-5554` or `--device <simulator UDID>`.

## Android emulator

```bash
sdkmanager "platform-tools" "emulator" "system-images;android-35;google_apis;arm64-v8a"    # x86_64 on Intel/Windows
avdmanager create avd -n testkit-api35 -k "system-images;android-35;google_apis;arm64-v8a" -d pixel_8
emulator -avd testkit-api35 -no-snapshot-save -no-boot-anim &            # add -no-window on CI
adb wait-for-device && adb shell getprop sys.boot_completed               # prints 1 when ready
# or let Maestro create and boot one like Maestro Cloud's: maestro start-device --platform android --device-os android-34
```

Install and inspect the build:

```bash
adb -s emulator-5554 install -r -g builds/app-staging.apk   # -r reinstall, -g grant runtime permissions (omit when testing prompts)
adb -s emulator-5554 shell dumpsys package com.example.app | grep -E "versionName|versionCode"
adb -s emulator-5554 shell pm clear com.example.app         # reset app data (same as clearState)
adb -s emulator-5554 logcat -d -t 500 > qa/runs/R/evidence/S1/logcat-TC-S1-004.txt   # crash evidence; check it for tokens before attaching
```

## iOS simulator (macOS + Xcode)

```bash
xcrun simctl list devices available | grep iPhone
xcrun simctl boot "iPhone 16" && xcrun simctl bootstatus "iPhone 16" -b
# or: maestro start-device --platform ios --device-os iOS-18-6 --device-model iPhone-16
xcrun simctl install booted builds/App-staging.app          # unzip first if the build is App.zip
xcrun simctl privacy booted reset all com.example.app       # reset permission answers
xcrun simctl get_app_container booted com.example.app       # check it is installed
xcrun simctl shutdown "iPhone 16"                           # when the stream is done, if you booted it
```

Simulators run only simulator builds (`.app` built for the simulator, arm64 on Apple Silicon). An `.ipa` is for real devices.

The first `maestro test` on a new simulator builds and installs Maestro's XCTest driver (about a minute); later runs are faster.

## Real devices

- Android: enable Developer options → USB debugging, connect, accept the RSA prompt, check `adb devices`. Install with `adb install`. Disable animations for stability: `adb shell settings put global window_animation_scale 0` (also `transition_animation_scale`, `animator_duration_scale`).
- iOS: Maestro supports physical iPhones only in recent versions and needs a development-signed build and a trusted device; if `maestro list-devices` does not show it, use a simulator or the team's device farm and report the limitation.
- Never use a personal phone with real accounts logged in. Use test devices.

## Store and internal builds

- Play internal testing / Firebase App Distribution / TestFlight builds are installed by a person or CI on a real device. The executor records the installed version and runs flows against it; it does not sign in to store accounts itself.
- `build.url_env` in config: download with the URL from that environment variable into `builds/` (git-ignored), never commit builds.

## Hybrid WebView debugging (Android)

```bash
adb shell 'grep -a webview_devtools_remote /proc/net/unix'      # find the socket (debuggable builds only)
adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>
curl -s http://127.0.0.1:9333/json                               # pages inside the WebView, with their URLs
```

Use the URL to test the web part with the `browser-testing` skill at the mobile viewport. Remove the forward afterwards: `adb forward --remove tcp:9333`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Java 17 or higher is required` | install JDK 17/21, set `JAVA_HOME` |
| `No devices found` / flows hang at start | boot the emulator/simulator first; `adb kill-server && adb start-server` |
| Element not found but visible | `maestro hierarchy` to see the real text/id; text may differ in case or have trailing spaces; WebView text can need `scrollUntilVisible` |
| iOS keyboard covers the button | `hideKeyboard` or tap outside |
| Flaky taps after navigation | `waitForAnimationToEnd` or `extendedWaitUntil` before the tap, not a fixed sleep |
