import Domain
import Foundation
import StorageKit
import Testing

@Test("GRDBChunkRepository should persist and search chunks")
func grdbRepositoryPersistsAndSearches() async throws {
    let tempDir = FileManager.default.temporaryDirectory
        .appendingPathComponent("filesmind-grdb-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)

    let dbURL = tempDir.appendingPathComponent("chunks.sqlite", isDirectory: false)
    let repository = try GRDBChunkRepository(databaseURL: dbURL)

    let documentID = UUID()
    let chunks = [
        Chunk(documentID: documentID, ordinal: 0, text: "apple banana"),
        Chunk(documentID: documentID, ordinal: 1, text: "orange kiwi"),
        Chunk(documentID: documentID, ordinal: 2, text: "banana pear")
    ]

    try await repository.upsert(chunks)
    let hits = try await repository.search(byKeyword: "banana", limit: 10)

    #expect(hits.count == 2)
    #expect(hits.map(\.ordinal) == [0, 2])
}
