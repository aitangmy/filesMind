import Domain
import Foundation
import TelemetryKit

public actor DocumentImportService: DocumentImporting {
    private let parser: DocumentParsing
    private let chunkRepository: ChunkRepository
    private let documentStore: (any ImportedDocumentStore)?
    private let telemetry: Telemetry

    public init(
        parser: DocumentParsing,
        chunkRepository: ChunkRepository,
        documentStore: (any ImportedDocumentStore)? = nil,
        telemetry: Telemetry = ConsoleTelemetry()
    ) {
        self.parser = parser
        self.chunkRepository = chunkRepository
        self.documentStore = documentStore
        self.telemetry = telemetry
    }

    public func importDocument(at fileURL: URL) async throws -> ParsedDocument {
        let parsed = try await parser.parse(fileURL: fileURL)
        try await chunkRepository.upsert(parsed.chunks)

        if let documentStore {
            let record = ImportedDocumentRecord(
                id: parsed.documentID,
                sourcePath: parsed.sourceURL.path(),
                title: parsed.title,
                sourceType: parsed.sourceType,
                chunkCount: parsed.chunks.count,
                lowQualityPages: parsed.lowQualityPages,
                importedAt: Date()
            )
            try await documentStore.upsertDocument(record, sections: parsed.sections)
        }

        telemetry.info(
            "Document imported: \(fileURL.lastPathComponent), type=\(parsed.sourceType.rawValue), chunks=\(parsed.chunks.count)"
        )

        return parsed
    }
}
