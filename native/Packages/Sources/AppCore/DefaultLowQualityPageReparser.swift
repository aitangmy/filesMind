import Domain
import Foundation
import TelemetryKit

public actor DefaultLowQualityPageReparser: LowQualityPageReparsing {
    private let parser: DocumentParsing
    private let telemetry: Telemetry

    public init(parser: DocumentParsing, telemetry: Telemetry = ConsoleTelemetry()) {
        self.parser = parser
        self.telemetry = telemetry
    }

    public func reparse(document: ImportedDocumentRecord, pages: [Int]) async throws -> [Int] {
        guard document.sourceType == .pdf else {
            return []
        }

        let fileURL = URL(fileURLWithPath: document.sourcePath)
        let reparsed = try await parser.parse(fileURL: fileURL)

        let stillLowSet = Set(reparsed.lowQualityPages)
        let resolved = pages.filter { !stillLowSet.contains($0) }

        telemetry.info(
            "Low-quality reparse complete for \(document.title). requested=\(pages.count), resolved=\(resolved.count), remaining=\(stillLowSet.count)"
        )

        return resolved
    }
}
