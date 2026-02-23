import Domain
import Foundation
import StorageKit
import TelemetryKit

public struct RankedChunk: Sendable, Equatable {
    public let chunk: Chunk
    public let score: Double

    public init(chunk: Chunk, score: Double) {
        self.chunk = chunk
        self.score = score
    }
}

public actor HybridSearchService {
    private let chunkRepository: ChunkRepository
    private let embeddingRepository: EmbeddingSearchRepository
    private let telemetry: Telemetry

    public init(
        chunkRepository: ChunkRepository,
        embeddingRepository: EmbeddingSearchRepository,
        telemetry: Telemetry = ConsoleTelemetry()
    ) {
        self.chunkRepository = chunkRepository
        self.embeddingRepository = embeddingRepository
        self.telemetry = telemetry
    }

    public func search(
        keyword: String,
        embedding: [Float],
        limit: Int,
        keywordWeight: Double = 0.4,
        vectorWeight: Double = 0.6
    ) async throws -> [RankedChunk] {
        let keywordHits = try await chunkRepository.search(byKeyword: keyword, limit: limit)
        let vectorHits = try await embeddingRepository.searchByVector(embedding, limit: limit)

        var scoreMap: [UUID: RankedChunk] = [:]

        for (index, chunk) in keywordHits.enumerated() {
            let score = keywordWeight * scoreForRank(index)
            scoreMap[chunk.id] = RankedChunk(chunk: chunk, score: score)
        }

        for (index, chunk) in vectorHits.enumerated() {
            let score = vectorWeight * scoreForRank(index)
            if let existing = scoreMap[chunk.id] {
                scoreMap[chunk.id] = RankedChunk(chunk: chunk, score: existing.score + score)
            } else {
                scoreMap[chunk.id] = RankedChunk(chunk: chunk, score: score)
            }
        }

        let ranked = scoreMap.values.sorted(by: { $0.score > $1.score }).prefix(max(limit, 0)).map { $0 }
        telemetry.info("Hybrid search complete. result_count=\(ranked.count)")
        return ranked
    }

    private func scoreForRank(_ index: Int) -> Double {
        1.0 / Double(index + 1)
    }
}
