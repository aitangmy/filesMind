import Domain
import Foundation
import TelemetryKit

public actor InMemoryChunkRepository: ChunkRepository, EmbeddingSearchRepository {
    private var chunksByID: [UUID: Chunk] = [:]
    private let telemetry: Telemetry

    public init(telemetry: Telemetry = ConsoleTelemetry()) {
        self.telemetry = telemetry
    }

    public func upsert(_ chunks: [Chunk]) async throws {
        for chunk in chunks {
            chunksByID[chunk.id] = chunk
        }
        telemetry.info("Upserted chunks: \(chunks.count)")
    }

    public func search(byKeyword keyword: String, limit: Int) async throws -> [Chunk] {
        let normalized = keyword.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty else {
            return []
        }

        return chunksByID.values
            .filter { $0.text.lowercased().contains(normalized) }
            .sorted(by: { $0.ordinal < $1.ordinal })
            .prefix(max(limit, 0))
            .map { $0 }
    }

    public func searchByVector(_ vector: [Float], limit: Int) async throws -> [Chunk] {
        guard !vector.isEmpty else {
            return []
        }
        // Phase 0 stub: vector search is not yet connected to sqlite-vss/usearch.
        return chunksByID.values
            .sorted(by: { $0.ordinal < $1.ordinal })
            .prefix(max(limit, 0))
            .map { $0 }
    }
}
