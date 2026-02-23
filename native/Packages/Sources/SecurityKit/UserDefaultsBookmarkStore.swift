import Domain
import Foundation

public actor UserDefaultsBookmarkStore: WorkspaceBookmarkStore {
    private let defaults: UserDefaults
    private let keyPrefix: String

    public init(defaults: UserDefaults = .standard, keyPrefix: String = "filesmind.workspace.bookmark") {
        self.defaults = defaults
        self.keyPrefix = keyPrefix
    }

    public func loadBookmark(for workspaceID: WorkspaceID) async throws -> Data? {
        defaults.data(forKey: key(for: workspaceID))
    }

    public func saveBookmark(_ data: Data, for workspaceID: WorkspaceID) async throws {
        defaults.set(data, forKey: key(for: workspaceID))
    }

    public func removeBookmark(for workspaceID: WorkspaceID) async throws {
        defaults.removeObject(forKey: key(for: workspaceID))
    }

    private func key(for workspaceID: WorkspaceID) -> String {
        "\(keyPrefix).\(workspaceID.rawValue)"
    }
}
