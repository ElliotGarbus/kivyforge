"""Maven channel resolution (android/02 channel 4) — hermetic via fake backend."""

from __future__ import annotations

from kivyforge.config.model import AndroidGradleConfig
from kivyforge.platforms.android.lock.maven import (
    GradleMavenResolver,
    resolve_gradle_pins,
)
from kivyforge.platforms.android.lock.model import (
    GradleArtifact,
    GradleResolvedModule,
)


class FakeGradle:
    def __init__(self, modules):
        self.modules = modules
        self.calls = 0

    def resolve(self, gradle, *, offline=False):
        self.calls += 1
        return self.modules


class TestResolveGradlePins:
    def test_no_deps_skips_gradle(self):
        backend = FakeGradle(())
        pins = resolve_gradle_pins(AndroidGradleConfig(), resolver=backend)
        assert not pins.declared
        assert backend.calls == 0  # never invoked without coordinates

    def test_declared_deps_resolved(self):
        modules = (
            GradleResolvedModule(
                coordinate="com.google.zxing:core:3.5.3",
                artifacts=(GradleArtifact(name="core-3.5.3.jar", sha256="a" * 64),),
            ),
        )
        backend = FakeGradle(modules)
        config = AndroidGradleConfig(
            dependencies=("com.google.zxing:core:3.5.3",),
            repositories=("https://maven.example/releases",),
        )
        pins = resolve_gradle_pins(config, resolver=backend)
        assert pins.declared
        assert pins.dependencies == ("com.google.zxing:core:3.5.3",)
        assert pins.repositories == ("https://maven.example/releases",)
        assert pins.resolved == modules
        assert backend.calls == 1

    def test_protocol_shape(self):
        # A fake satisfies the protocol without inheritance.
        backend: GradleMavenResolver = FakeGradle(())
        assert backend.resolve(AndroidGradleConfig()) == ()
