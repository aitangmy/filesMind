import Domain
import Foundation
import TelemetryKit

public struct PipelineRoutingDecision: Sendable, Equatable {
    public let pageIndex: Int
    public let requiresVLMFallback: Bool

    public init(pageIndex: Int, requiresVLMFallback: Bool) {
        self.pageIndex = pageIndex
        self.requiresVLMFallback = requiresVLMFallback
    }
}

public actor PipelineRouter {
    private let telemetry: Telemetry

    public init(telemetry: Telemetry = ConsoleTelemetry()) {
        self.telemetry = telemetry
    }

    public func route(
        assessments: [ParsePageAssessment],
        vlmFallbackThreshold: Double
    ) -> [PipelineRoutingDecision] {
        let decisions = assessments.map {
            PipelineRoutingDecision(
                pageIndex: $0.pageIndex,
                requiresVLMFallback: $0.qualityScore < vlmFallbackThreshold
            )
        }

        let fallbackCount = decisions.filter(\.requiresVLMFallback).count
        telemetry.info("Document pipeline routing complete. VLM fallback pages: \(fallbackCount)")
        return decisions
    }
}
