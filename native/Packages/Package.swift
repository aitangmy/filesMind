// swift-tools-version: 6.1
import PackageDescription

let package = Package(
    name: "FilesMindNative",
    defaultLocalization: "en",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(name: "Domain", targets: ["Domain"]),
        .library(name: "TelemetryKit", targets: ["TelemetryKit"]),
        .library(name: "SecurityKit", targets: ["SecurityKit"]),
        .library(name: "StorageKit", targets: ["StorageKit"]),
        .library(name: "DocumentPipeline", targets: ["DocumentPipeline"]),
        .library(name: "InferenceKit", targets: ["InferenceKit"]),
        .library(name: "SearchKit", targets: ["SearchKit"]),
        .library(name: "GraphEngine", targets: ["GraphEngine"]),
        .library(name: "ModelManager", targets: ["ModelManager"]),
        .library(name: "DesignSystem", targets: ["DesignSystem"]),
        .library(name: "AppCore", targets: ["AppCore"])
    ],
    targets: [
        .target(name: "Domain"),
        .target(name: "TelemetryKit", dependencies: ["Domain"]),
        .target(name: "SecurityKit", dependencies: ["Domain", "TelemetryKit"]),
        .target(name: "StorageKit", dependencies: ["Domain", "TelemetryKit"]),
        .target(name: "DocumentPipeline", dependencies: ["Domain", "TelemetryKit"]),
        .target(name: "InferenceKit", dependencies: ["Domain", "TelemetryKit"]),
        .target(name: "SearchKit", dependencies: ["Domain", "StorageKit", "TelemetryKit"]),
        .target(name: "GraphEngine", dependencies: ["Domain"]),
        .target(name: "ModelManager", dependencies: ["Domain", "SecurityKit", "TelemetryKit"]),
        .target(name: "DesignSystem"),
        .target(
            name: "AppCore",
            dependencies: [
                "Domain",
                "TelemetryKit",
                "SecurityKit",
                "StorageKit",
                "DocumentPipeline",
                "InferenceKit",
                "SearchKit",
                "GraphEngine",
                "ModelManager"
            ]
        ),
        .testTarget(name: "DomainTests", dependencies: ["Domain"]),
        .testTarget(name: "SecurityKitTests", dependencies: ["SecurityKit", "Domain"]),
        .testTarget(name: "GraphEngineTests", dependencies: ["GraphEngine", "Domain"])
    ]
)
