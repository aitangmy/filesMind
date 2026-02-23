import Domain
import SecurityKit
import Foundation
import Testing

@Test("SecurityScopedBookmarkManager authorize and resolve")
func authorizeAndResolveWorkspace() async throws {
    let suiteName = "filesmind.tests.\(UUID().uuidString)"
    guard let defaults = UserDefaults(suiteName: suiteName) else {
        throw FilesMindError.invalidState("Unable to create UserDefaults suite")
    }

    let store = UserDefaultsBookmarkStore(defaults: defaults, keyPrefix: "tests.bookmark")
    let manager = SecurityScopedBookmarkManager(store: store)

    let workspaceID = WorkspaceID("workspace-a")
    let tempDir = FileManager.default.temporaryDirectory
        .appendingPathComponent("filesmind-test-\(UUID().uuidString)", isDirectory: true)

    try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)

    let auth = try await manager.authorizeWorkspace(id: workspaceID, directoryURL: tempDir)
    #expect(auth.workspaceID == workspaceID)

    let resolved = try await manager.resolveAuthorization(id: workspaceID)
    #expect(resolved.workspaceID == workspaceID)
    #expect(!resolved.bookmarkData.isEmpty)

    let handle = try await manager.startScopedAccess(id: workspaceID)
    #expect(handle.workspaceID == workspaceID)
    await manager.stopScopedAccess(handle)
}
