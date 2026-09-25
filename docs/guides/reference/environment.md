---
title: Environment variables
sources:
  - kivyforge/platforms/__init__.py
  - kivyforge/report/console.py
  - kivyforge/platforms/android/signing.py
  - kivyforge/platforms/android/doctor.py
  - kivyforge/platforms/ios/xcode/commands.py
  - kivyforge/lock/wheelruntime/pbs_github.py
  - kivyforge/artifacts/cache.py
  - docs/design/common/02-cli-and-platform-resolution.md
---

# Environment variables

kivyforge reads the environment variables on this page. Use them for session
defaults, for secrets that must stay out of `pyproject.toml`, and to point
kivyforge at tools installed in non-default locations.

## Target selection

| Variable | Effect |
|---|---|
| `KIVYFORGE_PLATFORM` | Default target when you don't pass `-p`, for example `android` or its alias `win` for `windows`. `-p` overrides it. See [Choose a target platform](../concepts/choose-platform.md). |

## Output

| Variable | Effect |
|---|---|
| `NO_COLOR` | Disables coloured output. Any value counts, including `0`. |
| `FORCE_COLOR` | Forces coloured output, even when the output is not a terminal. `--no-color` and `NO_COLOR` both take precedence over it. |

## Signing

Keep signing passwords and identities out of `pyproject.toml`.

| Variable | Platform | Effect |
|---|---|---|
| `KIVYFORGE_KEYSTORE_PASSWORD` | Android | Password of the release keystore. `package` fails if it is unset. |
| `KIVYFORGE_KEY_PASSWORD` | Android | Password of the release key. If unset, the keystore password is used. |
| `KIVYFORGE_TEAM_ID` | iOS | Apple Developer Team ID. `--team-id` overrides it; it overrides `[tool.kivy.ios.signing].team_id`. |
| `KIVYFORGE_SIGNING_IDENTITY` | iOS | Signing identity. `--signing-identity` overrides it; it overrides `[tool.kivy.ios.signing].identity`. |

The two Android names are defaults. To read the passwords from different
variables, set `store_password_env` and `key_password_env` in
`[tool.kivy.android.signing]`. See the
[Android overlay reference](pyproject/android.md).

## Toolchain locations

| Variable | Platform | Effect |
|---|---|---|
| `ANDROID_HOME` | Android | Root of the Android SDK. Checked first. |
| `ANDROID_SDK_ROOT` | Android | Root of the Android SDK, used when `ANDROID_HOME` is unset or not a directory. If neither is set, kivyforge looks in `%LOCALAPPDATA%\Android\Sdk` on Windows, or `~/Android/Sdk` and `~/android-sdk` elsewhere. |
| `JAVA_HOME` | Android | JDK location that `doctor` checks when `java` is not on `PATH`. |

## Network

| Variable | Effect |
|---|---|
| `GH_TOKEN` | Token for the GitHub API, which `lock` queries to resolve the desktop Python runtime. Takes precedence over `GITHUB_TOKEN`. |
| `GITHUB_TOKEN` | Same, used when `GH_TOKEN` is unset. On GitHub Actions, set it from `secrets.GITHUB_TOKEN`. |

Unauthenticated, the GitHub API allows 60 requests per hour per IP address. A
token raises the limit to 5,000 per hour. An empty or whitespace-only value is
ignored, so an unset CI secret falls back to an anonymous request.

## Artifact cache location

kivyforge caches downloaded artifacts per user. On Linux, it honours the XDG base
directory convention.

| Host | Cache directory |
|---|---|
| Linux | `$XDG_CACHE_HOME/kivyforge/artifacts`, or `~/.cache/kivyforge/artifacts` if `XDG_CACHE_HOME` is unset |
| macOS | `~/Library/Caches/kivyforge/artifacts` |
| Windows | `%LOCALAPPDATA%\kivyforge\Cache\artifacts` |

## What's next

- [Choose a target platform](../concepts/choose-platform.md)
- [Drive kivyforge from CI or an agent](../guides/cross-platform/ci-and-agents.md)
- [Signing prerequisites](../troubleshooting/signing-prerequisites.md)
