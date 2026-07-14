---
name: macos native stage extraction
overview: Extract the pure native-binary staging mechanics out of the macOS native_stage.py into a shared kivyforge/artifacts/native_stage_util.py, and refactor macOS onto it in the same change. Behavior-preserving; the existing macOS tests are the safety net. This is Step 3 of the Linux native-binaries plan, done first on macOS so Linux (and later Windows) can consume the shared module.
todos:
  - id: create-util
    content: "Create kivyforge/artifacts/native_stage_util.py: define NativeStageError; move _stage_one/_fetch/_extract_zip/_claim/_make_executable/_safe_extract from the macOS module, raising NativeStageError and using a bin_label param in the collision message; add public stage_binaries(binaries, parent_dir, *, project_root, cache, no_cache, bin_label); import LockedNativeBinary only under TYPE_CHECKING."
    status: pending
  - id: refactor-macos
    content: "Reduce kivyforge/platforms/macos/native_stage.py to a thin wrapper: keep the public stage_native_binaries(lock, resources, ...) signature, delegate to stage_binaries with bin_label='Contents/Resources/bin', and catch NativeStageError -> re-raise AppBundleError(str(exc)) from exc. Remove the now-moved private helpers."
    status: pending
  - id: util-tests
    content: "Add tests/artifacts/test_native_stage_util.py: platform-agnostic tests for _safe_extract traversal rejection and _claim collision (assert NativeStageError), plus happy-path single-file and zip staging using an arbitrary parent_dir and bin_label."
    status: pending
  - id: verify-green
    content: Run the macOS native-stage + bundle tests (unchanged, green), the new util tests, and ruff on the touched files; then full pytest with coverage >= 80% to confirm no regressions.
    status: pending
isProject: false
---

# macOS native-stage helper extraction

Lift the platform-neutral staging mechanics from [kivyforge/platforms/macos/native_stage.py](kivyforge/platforms/macos/native_stage.py) into a new shared module, and reduce the macOS module to a thin, behavior-identical wrapper. No functional change on macOS; the existing tests are the contract.

## Why now
Linux (and imminently Windows) need the same `_safe_extract` / `_claim` / `_make_executable` / `_fetch` mechanics. `_safe_extract` (zip path-traversal) is security-sensitive and must live in exactly one audited place rather than being copied per platform. Doing the extraction on macOS first — where a full test suite already exists — proves it before any second consumer.

## Design decisions
- **Neutral error, translated by the caller (matches an existing repo pattern).** The shared util raises its own `NativeStageError`; the macOS wrapper catches it and re-raises `AppBundleError(str(exc))`. This mirrors how [kivyforge/lock/wheelruntime/native_binaries.py](kivyforge/lock/wheelruntime/native_binaries.py) raises `NativeBinaryResolverError` and [kivyforge/lock/wheelruntime/builder.py](kivyforge/lock/wheelruntime/builder.py) re-raises it as `WheelRuntimeBuildError`. Preferred over threading an `error` class through every helper.
- **`bin_label` parameter for messages.** The collision message currently hardcodes `Contents/Resources/bin`; the util takes a `bin_label` string so Linux can pass `usr/bin` later. macOS passes `"Contents/Resources/bin"`, keeping the message byte-identical.
- **Preserve the public API.** Keep `stage_native_binaries(lock, resources, *, project_root, cache=None, no_cache=False)` in the macOS module with the same name/signature, so [kivyforge/platforms/macos/bundle.py](kivyforge/platforms/macos/bundle.py) and [tests/platforms/macos/test_bundle.py](tests/platforms/macos/test_bundle.py) are untouched.
- **Avoid import cycles.** `kivyforge/artifacts/` already depends on `lock` (download.py imports `lock.find_links`). Import `LockedNativeBinary` only under `TYPE_CHECKING` in the util (runtime code only reads `.name/.url/.path/.sha256`).

## Proposed shared module: `kivyforge/artifacts/native_stage_util.py`

```python
class NativeStageError(Exception):
    """A native-binary staging failure (translated to the caller's bundle error)."""

def stage_binaries(
    binaries,               # tuple[LockedNativeBinary, ...]
    parent_dir: Path,       # bin/ is created under this (macOS: Contents/Resources)
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
    bin_label: str,         # human path used in the collision message
) -> None:
    if not binaries:
        return
    cache = cache or ArtifactCache()
    bin_dir = parent_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    claimed: dict[str, str] = {}
    for entry in binaries:
        _stage_one(entry, bin_dir, claimed, project_root=project_root,
                   cache=cache, no_cache=no_cache, bin_label=bin_label)
```

Move `_stage_one`, `_fetch`, `_extract_zip`, `_claim`, `_make_executable`, `_safe_extract` verbatim, changing only `AppBundleError` -> `NativeStageError` and using `bin_label` in the `_claim` message.

## Resulting macOS wrapper: `kivyforge/platforms/macos/native_stage.py`

```python
from kivyforge.artifacts.native_stage_util import NativeStageError, stage_binaries
from . import AppBundleError

def stage_native_binaries(lock, resources, *, project_root, cache=None, no_cache=False):
    try:
        stage_binaries(
            lock.native_binaries, resources,
            project_root=project_root, cache=cache, no_cache=no_cache,
            bin_label="Contents/Resources/bin",
        )
    except NativeStageError as exc:
        raise AppBundleError(str(exc)) from exc
```

The `str(exc)` translation preserves every message, so the existing assertions in [tests/platforms/macos/test_native_stage.py](tests/platforms/macos/test_native_stage.py) (`match="unsafe path"`, `match=r"colliding path bin/tool"`, and `pytest.raises(AppBundleError)`) all still pass.

## Verification
- `pytest tests/platforms/macos/test_native_stage.py tests/platforms/macos/test_bundle.py` green, unchanged.
- New `tests/artifacts/test_native_stage_util.py` covers `_safe_extract` traversal rejection and `_claim` collision raising `NativeStageError`, plus a happy-path single-file + zip stage — all platform-agnostic (arbitrary `parent_dir` + `bin_label`).
- `ruff` clean on the touched files; full `pytest` (coverage >= 80%) green.

## Out of scope
- Any Linux/Windows wiring, `.tar.gz` support, or the ELF/PE arch checks — those stay in the Linux/Windows plans and consume this module afterward. This change is a pure, behavior-preserving macOS refactor.