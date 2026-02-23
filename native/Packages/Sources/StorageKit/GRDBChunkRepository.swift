import Domain
import Foundation
import GRDB
import TelemetryKit

public actor GRDBChunkRepository: ChunkRepository, EmbeddingSearchRepository {
    private let dbQueue: DatabaseQueue
    private let telemetry: Telemetry

    public init(databaseURL: URL, telemetry: Telemetry = ConsoleTelemetry()) throws {
        self.telemetry = telemetry

        let directory = databaseURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        self.dbQueue = try DatabaseQueue(path: databaseURL.path)

        var migrator = DatabaseMigrator()
        migrator.registerMigration("v1_create_chunks") { db in
            try db.create(table: "chunks", ifNotExists: true) { table in
                table.column("id", .text).primaryKey()
                table.column("document_id", .text).notNull()
                table.column("ordinal", .integer).notNull()
                table.column("text", .text).notNull()
                table.column("created_at", .datetime).notNull().defaults(sql: "CURRENT_TIMESTAMP")
                table.column("updated_at", .datetime).notNull().defaults(sql: "CURRENT_TIMESTAMP")
            }

            try db.create(
                index: "idx_chunks_document_ordinal",
                on: "chunks",
                columns: ["document_id", "ordinal"],
                ifNotExists: true
            )
        }

        try migrator.migrate(dbQueue)
        telemetry.info("GRDB chunk repository initialized at: \(databaseURL.path)")
    }

    public func upsert(_ chunks: [Chunk]) async throws {
        guard !chunks.isEmpty else { return }

        try await dbQueue.write { db in
            for chunk in chunks {
                try db.execute(
                    sql: """
                    INSERT INTO chunks (id, document_id, ordinal, text, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                      document_id = excluded.document_id,
                      ordinal = excluded.ordinal,
                      text = excluded.text,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    arguments: [chunk.id.uuidString, chunk.documentID.uuidString, chunk.ordinal, chunk.text]
                )
            }
        }

        telemetry.info("Persisted chunks via GRDB: \(chunks.count)")
    }

    public func search(byKeyword keyword: String, limit: Int) async throws -> [Chunk] {
        let normalized = keyword.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty else {
            return []
        }

        return try await dbQueue.read { db in
            let rows = try Row.fetchAll(
                db,
                sql: """
                SELECT id, document_id, ordinal, text
                FROM chunks
                WHERE lower(text) LIKE ?
                ORDER BY ordinal ASC
                LIMIT ?
                """,
                arguments: ["%\(normalized)%", max(limit, 0)]
            )

            return rows.compactMap(Self.makeChunk(from:))
        }
    }

    public func searchByVector(_ vector: [Float], limit: Int) async throws -> [Chunk] {
        guard !vector.isEmpty else {
            return []
        }

        // Phase 1.5 fallback: vector extension not wired yet.
        return try await dbQueue.read { db in
            let rows = try Row.fetchAll(
                db,
                sql: """
                SELECT id, document_id, ordinal, text
                FROM chunks
                ORDER BY ordinal ASC
                LIMIT ?
                """,
                arguments: [max(limit, 0)]
            )
            return rows.compactMap(Self.makeChunk(from:))
        }
    }

    private static func makeChunk(from row: Row) -> Chunk? {
        guard
            let idString: String = row["id"],
            let documentIDString: String = row["document_id"],
            let id = UUID(uuidString: idString),
            let documentID = UUID(uuidString: documentIDString)
        else {
            return nil
        }

        let ordinal: Int = row["ordinal"]
        let text: String = row["text"]

        return Chunk(id: id, documentID: documentID, ordinal: ordinal, text: text)
    }
}
