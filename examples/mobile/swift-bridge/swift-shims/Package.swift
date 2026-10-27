// swift-tools-version:5.9
import PackageDescription

// The shim pyobjus calls. Every class Python uses is an NSObject subclass
// with an explicit @objc name. The product is dynamic so that kivyforge has
// a framework to embed; pyobjus finds the classes at runtime.
let package = Package(
    name: "SwiftBridge",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "SwiftBridge", type: .dynamic, targets: ["SwiftBridge"]),
    ],
    targets: [
        .target(name: "SwiftBridge"),
    ]
)
