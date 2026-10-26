// swift-tools-version:5.9
import PackageDescription

// A local Objective-C package that runs before Python starts. Its `+load`
// installs app-delegate methods on SDL's delegate class; see
// Sources/LifecycleHook/LifecycleHook.m. kivyforge wires it in through the
// `path` form of [tool.kivy.ios.native.swift_packages].
//
// The product is `.dynamic`, so kivyforge embeds it as a framework. `.static`
// works too: Xcode links a source target as one object file, so `+load` is
// never stripped. Declare a static product with `embed = false`.
let package = Package(
    name: "LifecycleHook",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "LifecycleHook", type: .dynamic, targets: ["LifecycleHook"]),
    ],
    targets: [
        .target(name: "LifecycleHook"),
    ]
)
