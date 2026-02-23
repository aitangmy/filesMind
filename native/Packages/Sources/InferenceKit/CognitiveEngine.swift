import Domain
import Foundation
import TelemetryKit

public struct InferenceRequest: Sendable {
    public let systemPrompt: String
    public let userPrompt: String
    public let schemaName: String

    public init(systemPrompt: String, userPrompt: String, schemaName: String) {
        self.systemPrompt = systemPrompt
        self.userPrompt = userPrompt
        self.schemaName = schemaName
    }
}

public protocol CognitiveEngine: Sendable {
    func generateStructuredJSON(_ request: InferenceRequest) async throws -> String
}

public final class StubCognitiveEngine: CognitiveEngine, @unchecked Sendable {
    private let telemetry: Telemetry

    public init(telemetry: Telemetry = ConsoleTelemetry()) {
        self.telemetry = telemetry
    }

    public func generateStructuredJSON(_ request: InferenceRequest) async throws -> String {
        telemetry.warning("StubCognitiveEngine used for schema: \(request.schemaName)")
        throw FilesMindError.notSupported("MLX runtime is not wired in phase 0")
    }
}
