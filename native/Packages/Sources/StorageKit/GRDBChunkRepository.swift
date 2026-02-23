import Domain
import Foundation
import GRDB
import TelemetryKit

public actor GRDBChunkRepository: ChunkRepository, EmbeddingSearchRepository, ImportedDocumentStore {
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
                table.column("source_page_index", .integer)
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

        migrator.registerMigration("v2_create_documents") { db in
            try db.create(table: "documents", ifNotExists: true) { table in
                table.column("id", .text).primaryKey()
                table.column("source_path", .text).notNull()
                table.column("title", .text).notNull()
                table.column("source_type", .text).notNull()
                table.column("chunk_count", .integer).notNull()
                table.column("low_quality_pages_json", .text).notNull()
                table.column("imported_at", .datetime).notNull()
                table.column("updated_at", .datetime).notNull().defaults(sql: "CURRENT_TIMESTAMP")
            }

            try db.create(table: "document_sections", ifNotExists: true) { table in
                table.column("id", .text).primaryKey()
                table.column("document_id", .text).notNull().indexed()
                table.column("level", .integer).notNull()
                table.column("title", .text).notNull()
                table.column("chunk_start_ordinal", .integer).notNull()
            }
        }

        migrator.registerMigration("v3_add_chunk_source_page_index") { db in
            let columns = try db.columns(in: "chunks").map(\.name)
            if !columns.contains("source_page_index") {
                try db.alter(table: "chunks") { table in
                    table.add(column: "source_page_index", .integer)
                }
            }
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
                    INSERT INTO chunks (id, document_id, ordinal, text, source_page_index, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                      document_id = excluded.document_id,
                      ordinal = excluded.ordinal,
                      text = excluded.text,
                      source_page_index = excluded.source_page_index,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    arguments: [
                        chunk.id.uuidString,
                        chunk.documentID.uuidString,
                        chunk.ordinal,
                        chunk.text,
                        chunk.sourcePageIndex
                    ]
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
                SELECT id, document_id, ordinal, text, source_page_index
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
                SELECT id, document_id, ordinal, text, source_page_index
                FROM chunks
                ORDER BY ordinal ASC
                LIMIT ?
                """,
                arguments: [max(limit, 0)]
            )
            return rows.compactMap(Self.makeChunk(from:))
        }
    }

    public func upsertDocument(_ document: ImportedDocumentRecord, sections: [ParsedSection]) async throws {
        let lowQualityPagesJSON = try Self.encodeLowQualityPages(document.lowQualityPages)

        try await dbQueue.write { db in
            try db.execute(
                sql: """
                INSERT INTO documents (
                  id, source_path, title, source_type, chunk_count, low_quality_pages_json, imported_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                  source_path = excluded.source_path,
                  title = excluded.title,
                  source_type = excluded.source_type,
                  chunk_count = excluded.chunk_count,
                  low_quality_pages_json = excluded.low_quality_pages_json,
                  imported_at = excluded.imported_at,
                  updated_at = CURRENT_TIMESTAMP
                """,
                arguments: [
                    document.id.uuidString,
                    document.sourcePath,
                    document.title,
                    document.sourceType.rawValue,
                    document.chunkCount,
                    lowQualityPagesJSON,
                    document.importedAt
                ]
            )

            try db.execute(
                sql: "DELETE FROM document_sections WHERE document_id = ?",
                arguments: [document.id.uuidString]
            )

            for section in sections {
                try db.execute(
                    sql: """
                    INSERT INTO document_sections (id, document_id, level, title, chunk_start_ordinal)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    arguments: [
                        section.id.uuidString,
                        section.documentID.uuidString,
                        section.level,
                        section.title,
                        section.chunkStartOrdinal
                    ]
                )
            }
        }
    }

    public func recentDocuments(limit: Int) async throws -> [ImportedDocumentRecord] {
        try await dbQueue.read { db in
            let rows = try Row.fetchAll(
                db,
                sql: """
                SELECT id, source_path, title, source_type, chunk_count, low_quality_pages_json, imported_at
                FROM documents
                ORDER BY imported_at DESC
                LIMIT ?
                """,
                arguments: [max(limit, 0)]
            )
            return try rows.compactMap(Self.makeDocument(from:))
        }
    }

    public func sections(for documentID: UUID) async throws -> [ParsedSection] {
        try await dbQueue.read { db in
            let rows = try Row.fetchAll(
                db,
                sql: """
                SELECT id, document_id, level, title, chunk_start_ordinal
                FROM document_sections
                WHERE document_id = ?
                ORDER BY chunk_start_ordinal ASC
                """,
                arguments: [documentID.uuidString]
            )
            return rows.compactMap(Self.makeSection(from:))
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
        let sourcePageIndex: Int? = row["source_page_index"]

        return Chunk(
            id: id,
            documentID: documentID,
            ordinal: ordinal,
            text: text,
            sourcePageIndex: sourcePageIndex
        )
    }

    private static func makeSection(from row: Row) -> ParsedSection? {
        guard
            let idString: String = row["id"],
            let documentIDString: String = row["document_id"],
            let id = UUID(uuidString: idString),
            let documentID = UUID(uuidString: documentIDString)
        else {
            return nil
        }

        let level: Int = row["level"]
        let title: String = row["title"]
        let ordinal: Int = row["chunk_start_ordinal"]
        return ParsedSection(id: id, documentID: documentID, level: level, title: title, chunkStartOrdinal: ordinal)
    }

    private static func makeDocument(from row: Row) throws -> ImportedDocumentRecord? {
        guard
            let idString: String = row["id"],
            let id = UUID(uuidString: idString),
            let sourceTypeRaw: String = row["source_type"],
            let sourceType = DocumentSourceType(rawValue: sourceTypeRaw)
        else {
            return nil
        }

        let sourcePath: String = row["source_path"]
        let title: String = row["title"]
        let chunkCount: Int = row["chunk_count"]
        let importedAt: Date = row["imported_at"]
        let lowQualityPagesJSONString: String = row["low_quality_pages_json"]
        let lowQualityPages = try decodeLowQualityPages(lowQualityPagesJSONString)

        return ImportedDocumentRecord(
            id: id,
            sourcePath: sourcePath,
            title: title,
            sourceType: sourceType,
            chunkCount: chunkCount,
            lowQualityPages: lowQualityPages,
            importedAt: importedAt
        )
    }

    private static func encodeLowQualityPages(_ pages: [Int]) throws -> String {
        let data = try JSONEncoder().encode(pages)
        guard let string = String(data: data, encoding: .utf8) else {
            throw FilesMindError.validationFailed("Unable to encode low quality pages")
        }
        return string
    }

    private static func decodeLowQualityPages(_ string: String) throws -> [Int] {
        guard let data = string.data(using: .utf8) else {
            throw FilesMindError.validationFailed("Invalid low quality pages payload")
        }
        return try JSONDecoder().decode([Int].self, from: data)
    }
}
