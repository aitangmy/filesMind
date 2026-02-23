import Foundation

public enum FilesMindError: Error, Sendable {
    case notFound(String)
    case invalidState(String)
    case unauthorized(String)
    case validationFailed(String)
    case notSupported(String)
}

public struct WorkspaceID: Hashable, Codable, Sendable {
    public let rawValue: String

    public init(_ rawValue: String) {
        self.rawValue = rawValue
    }
}

public struct WorkspaceAuthorization: Sendable, Equatable {
    public let workspaceID: WorkspaceID
    public let directoryURL: URL
    public let bookmarkData: Data
    public let isStale: Bool

    public init(
        workspaceID: WorkspaceID,
        directoryURL: URL,
        bookmarkData: Data,
        isStale: Bool
    ) {
        self.workspaceID = workspaceID
        self.directoryURL = directoryURL
        self.bookmarkData = bookmarkData
        self.isStale = isStale
    }
}

public struct WorkspaceAccessHandle: Sendable {
    public let workspaceID: WorkspaceID
    public let directoryURL: URL
    public let beganScopedAccess: Bool

    public init(workspaceID: WorkspaceID, directoryURL: URL, beganScopedAccess: Bool) {
        self.workspaceID = workspaceID
        self.directoryURL = directoryURL
        self.beganScopedAccess = beganScopedAccess
    }
}

public enum ModelTier: String, Codable, Sendable, CaseIterable {
    case lite
    case standard
    case pro
}

public struct ModelDescriptor: Identifiable, Codable, Sendable, Equatable {
    public var id: String { modelID }

    public let modelID: String
    public let displayName: String
    public let tier: ModelTier
    public let remoteURL: URL
    public let sha256: String
    public let bytes: Int64

    public init(
        modelID: String,
        displayName: String,
        tier: ModelTier,
        remoteURL: URL,
        sha256: String,
        bytes: Int64
    ) {
        self.modelID = modelID
        self.displayName = displayName
        self.tier = tier
        self.remoteURL = remoteURL
        self.sha256 = sha256
        self.bytes = bytes
    }
}

public struct Chunk: Sendable, Equatable {
    public let id: UUID
    public let documentID: UUID
    public let ordinal: Int
    public let text: String

    public init(id: UUID = UUID(), documentID: UUID, ordinal: Int, text: String) {
        self.id = id
        self.documentID = documentID
        self.ordinal = ordinal
        self.text = text
    }
}

public struct GraphNode: Identifiable, Sendable, Equatable {
    public let id: UUID
    public let title: String
    public let rect: Rect

    public init(id: UUID = UUID(), title: String, rect: Rect) {
        self.id = id
        self.title = title
        self.rect = rect
    }
}

public struct Rect: Sendable, Equatable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double

    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    }

    public var minX: Double { x }
    public var maxX: Double { x + width }
    public var minY: Double { y }
    public var maxY: Double { y + height }

    public func contains(_ point: (x: Double, y: Double)) -> Bool {
        point.x >= minX && point.x <= maxX && point.y >= minY && point.y <= maxY
    }

    public func intersects(_ other: Rect) -> Bool {
        !(other.minX > maxX || other.maxX < minX || other.minY > maxY || other.maxY < minY)
    }
}

public struct ParsePageAssessment: Sendable, Equatable {
    public let pageIndex: Int
    public let qualityScore: Double

    public init(pageIndex: Int, qualityScore: Double) {
        self.pageIndex = pageIndex
        self.qualityScore = qualityScore
    }
}
