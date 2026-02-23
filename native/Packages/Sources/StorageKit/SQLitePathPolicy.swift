import Foundation

public enum SQLitePathPolicy {
    public static func workspaceDatabaseURL(root: URL, workspaceID: String) -> URL {
        root
            .appendingPathComponent("Storage", isDirectory: true)
            .appendingPathComponent("\(workspaceID).sqlite", isDirectory: false)
    }

    public static func ensureStorageDirectory(root: URL) throws {
        let dir = root.appendingPathComponent("Storage", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }
}
