import Domain
import SecurityKit
import Foundation
import Testing

@Test("UserDefaults bookmark roundtrip")
func userDefaultsBookmarkRoundtrip() async throws {
    let suiteName = "filesmind.tests.\(UUID().uuidString)"
    guard let defaults = UserDefaults(suiteName: suiteName) else {
        throw FilesMindError.invalidState("Unable to create UserDefaults suite")
    }

    let store = UserDefaultsBookmarkStore(defaults: defaults, keyPrefix: "tests.bookmark")
    let workspaceID = WorkspaceID("ws-1")
    let payload = Data("bookmark".utf8)

    try await store.saveBookmark(payload, for: workspaceID)
    let loaded = try await store.loadBookmark(for: workspaceID)

    #expect(loaded == payload)
}
