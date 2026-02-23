import Domain
import Foundation
import TelemetryKit

public actor DocumentImportService: DocumentImporting {
    private let parser: DocumentParsing
    private let chunkRepository: ChunkRepository
    private let telemetry: Telemetry

    public init(
        parser: DocumentParsing,
        chunkRepository: ChunkRepository,
        telemetry: Telemetry = ConsoleTelemetry()
    ) {
        self.parser = parser
        self.chunkRepository = chunkRepository
        self.telemetry = telemetry
    }

    public func importDocument(at fileURL: URL) async throws -> ParsedDocument {
        let parsed = try await parser.parse(fileURL: fileURL)
        try await chunkRepository.upsert(parsed.chunks)

        telemetry.info(
            "Document imported: \(fileURL.lastPathComponent), type=\(parsed.sourceType.rawValue), chunks=\(parsed.chunks.count)"
        )

        return parsed
    }
}
