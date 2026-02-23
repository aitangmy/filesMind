import Domain
import Foundation
import SecurityKit
import TelemetryKit

public actor DefaultModelManager: ModelManaging {
    private let catalog: ModelCatalogProviding
    private let validator: ModelArtifactValidating
    private let fileManager: FileManager
    private let installRoot: URL
    private let telemetry: Telemetry

    public init(
        catalog: ModelCatalogProviding,
        validator: ModelArtifactValidating,
        installRoot: URL,
        fileManager: FileManager = .default,
        telemetry: Telemetry = ConsoleTelemetry()
    ) {
        self.catalog = catalog
        self.validator = validator
        self.installRoot = installRoot
        self.fileManager = fileManager
        self.telemetry = telemetry
    }

    public func install(modelID: String) async throws -> URL {
        let manifest = try await catalog.fetchManifest()
        guard let descriptor = manifest.first(where: { $0.modelID == modelID }) else {
            throw FilesMindError.notFound("Model not found: \(modelID)")
        }

        let modelDir = installRoot.appendingPathComponent(descriptor.modelID, isDirectory: true)
        try fileManager.createDirectory(at: modelDir, withIntermediateDirectories: true)

        let destination = modelDir.appendingPathComponent("model.safetensors", isDirectory: false)
        let (tmpURL, _) = try await URLSession.shared.download(from: descriptor.remoteURL)

        if fileManager.fileExists(atPath: destination.path) {
            try fileManager.removeItem(at: destination)
        }
        try fileManager.moveItem(at: tmpURL, to: destination)

        try await validator.validateArtifact(at: destination, expectedSHA256: descriptor.sha256)
        telemetry.info("Model installed: \(descriptor.modelID)")
        return destination
    }
}
