import Foundation

public protocol WorkspaceBookmarkStore: Sendable {
    func loadBookmark(for workspaceID: WorkspaceID) async throws -> Data?
    func saveBookmark(_ data: Data, for workspaceID: WorkspaceID) async throws
    func removeBookmark(for workspaceID: WorkspaceID) async throws
}

public protocol WorkspaceAuthorizationManaging: Sendable {
    func authorizeWorkspace(id: WorkspaceID, directoryURL: URL) async throws -> WorkspaceAuthorization
    func resolveAuthorization(id: WorkspaceID) async throws -> WorkspaceAuthorization
    func startScopedAccess(id: WorkspaceID) async throws -> WorkspaceAccessHandle
    func stopScopedAccess(_ handle: WorkspaceAccessHandle) async
}

public protocol ModelCatalogProviding: Sendable {
    func fetchManifest() async throws -> [ModelDescriptor]
}

public protocol ModelArtifactValidating: Sendable {
    func validateArtifact(at url: URL, expectedSHA256: String) async throws
}

public protocol ModelManaging: Sendable {
    func install(modelID: String) async throws -> URL
}

public protocol DocumentParsing: Sendable {
    func parse(fileURL: URL) async throws -> ParsedDocument
}

public protocol DocumentImporting: Sendable {
    func importDocument(at fileURL: URL) async throws -> ParsedDocument
}

public protocol ChunkRepository: Sendable {
    func upsert(_ chunks: [Chunk]) async throws
    func search(byKeyword keyword: String, limit: Int) async throws -> [Chunk]
}

public protocol EmbeddingSearchRepository: Sendable {
    func searchByVector(_ vector: [Float], limit: Int) async throws -> [Chunk]
}

public protocol Telemetry: Sendable {
    func info(_ message: String)
    func warning(_ message: String)
    func error(_ message: String)
}
