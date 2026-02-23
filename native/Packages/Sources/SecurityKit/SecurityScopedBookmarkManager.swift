import Domain
import Foundation
import TelemetryKit

public actor SecurityScopedBookmarkManager: WorkspaceAuthorizationManaging {
    private let store: WorkspaceBookmarkStore
    private let telemetry: Telemetry

    public init(store: WorkspaceBookmarkStore, telemetry: Telemetry = ConsoleTelemetry()) {
        self.store = store
        self.telemetry = telemetry
    }

    public func authorizeWorkspace(id: WorkspaceID, directoryURL: URL) async throws -> WorkspaceAuthorization {
        let bookmarkData = try makeBookmarkData(for: directoryURL)
        try await store.saveBookmark(bookmarkData, for: id)

        telemetry.info("Workspace authorized: \(id.rawValue)")

        return WorkspaceAuthorization(
            workspaceID: id,
            directoryURL: directoryURL,
            bookmarkData: bookmarkData,
            isStale: false
        )
    }

    public func resolveAuthorization(id: WorkspaceID) async throws -> WorkspaceAuthorization {
        guard let bookmarkData = try await store.loadBookmark(for: id) else {
            throw FilesMindError.notFound("Bookmark missing for workspace \(id.rawValue)")
        }

        var isStale = false
        let url = try resolveBookmark(bookmarkData, isStale: &isStale)

        if isStale {
            telemetry.warning("Stale bookmark detected for workspace: \(id.rawValue)")
            let refreshed = try makeBookmarkData(for: url)
            try await store.saveBookmark(refreshed, for: id)
            return WorkspaceAuthorization(
                workspaceID: id,
                directoryURL: url,
                bookmarkData: refreshed,
                isStale: true
            )
        }

        return WorkspaceAuthorization(
            workspaceID: id,
            directoryURL: url,
            bookmarkData: bookmarkData,
            isStale: false
        )
    }

    public func startScopedAccess(id: WorkspaceID) async throws -> WorkspaceAccessHandle {
        let authorization = try await resolveAuthorization(id: id)

#if os(macOS)
        let began = authorization.directoryURL.startAccessingSecurityScopedResource()
        if !began {
            throw FilesMindError.unauthorized("Unable to start security-scoped access for workspace \(id.rawValue)")
        }
#else
        let began = false
#endif

        telemetry.info("Scoped access started for workspace: \(id.rawValue)")

        return WorkspaceAccessHandle(
            workspaceID: id,
            directoryURL: authorization.directoryURL,
            beganScopedAccess: began
        )
    }

    public func stopScopedAccess(_ handle: WorkspaceAccessHandle) async {
#if os(macOS)
        if handle.beganScopedAccess {
            handle.directoryURL.stopAccessingSecurityScopedResource()
        }
#endif
        telemetry.info("Scoped access stopped for workspace: \(handle.workspaceID.rawValue)")
    }

    private func makeBookmarkData(for directoryURL: URL) throws -> Data {
#if os(macOS)
        return try directoryURL.bookmarkData(
            options: [.withSecurityScope],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
#else
        guard let data = directoryURL.absoluteString.data(using: .utf8) else {
            throw FilesMindError.validationFailed("Unable to encode fallback bookmark data")
        }
        return data
#endif
    }

    private func resolveBookmark(_ data: Data, isStale: inout Bool) throws -> URL {
#if os(macOS)
        return try URL(
            resolvingBookmarkData: data,
            options: [.withSecurityScope],
            relativeTo: nil,
            bookmarkDataIsStale: &isStale
        )
#else
        guard let string = String(data: data, encoding: .utf8), let url = URL(string: string) else {
            throw FilesMindError.validationFailed("Unable to decode fallback bookmark data")
        }
        return url
#endif
    }
}
