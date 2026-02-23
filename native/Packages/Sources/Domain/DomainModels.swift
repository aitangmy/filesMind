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

public enum ImportJobStatus: String, Sendable, Equatable, Codable {
    case queued
    case parsing
    case indexed
    case failed
}

public struct ImportJob: Identifiable, Sendable, Equatable, Codable {
    public let id: UUID
    public let fileURL: URL
    public let createdAt: Date
    public var status: ImportJobStatus
    public var progress: Double
    public var message: String?

    public init(
        id: UUID = UUID(),
        fileURL: URL,
        createdAt: Date = Date(),
        status: ImportJobStatus,
        progress: Double,
        message: String? = nil
    ) {
        self.id = id
        self.fileURL = fileURL
        self.createdAt = createdAt
        self.status = status
        self.progress = progress
        self.message = message
    }
}

public enum DocumentSourceType: String, Sendable, Equatable, Codable {
    case markdown
    case pdf
}

public struct ParsedSection: Identifiable, Sendable, Equatable, Codable {
    public let id: UUID
    public let documentID: UUID
    public let level: Int
    public let title: String
    public let chunkStartOrdinal: Int

    public init(
        id: UUID = UUID(),
        documentID: UUID,
        level: Int,
        title: String,
        chunkStartOrdinal: Int
    ) {
        self.id = id
        self.documentID = documentID
        self.level = level
        self.title = title
        self.chunkStartOrdinal = chunkStartOrdinal
    }
}

public struct ParsedDocument: Sendable, Equatable {
    public let documentID: UUID
    public let sourceURL: URL
    public let title: String
    public let sourceType: DocumentSourceType
    public let chunks: [Chunk]
    public let sections: [ParsedSection]
    public let lowQualityPages: [Int]
    public let fallbackPageCount: Int

    public init(
        documentID: UUID = UUID(),
        sourceURL: URL,
        title: String,
        sourceType: DocumentSourceType,
        chunks: [Chunk],
        sections: [ParsedSection] = [],
        lowQualityPages: [Int] = [],
        fallbackPageCount: Int? = nil
    ) {
        self.documentID = documentID
        self.sourceURL = sourceURL
        self.title = title
        self.sourceType = sourceType
        self.chunks = chunks
        self.sections = sections
        self.lowQualityPages = lowQualityPages
        self.fallbackPageCount = fallbackPageCount ?? lowQualityPages.count
    }
}

public struct ImportedDocumentRecord: Identifiable, Sendable, Equatable, Codable {
    public let id: UUID
    public let sourcePath: String
    public let title: String
    public let sourceType: DocumentSourceType
    public let chunkCount: Int
    public let lowQualityPages: [Int]
    public let importedAt: Date

    public init(
        id: UUID,
        sourcePath: String,
        title: String,
        sourceType: DocumentSourceType,
        chunkCount: Int,
        lowQualityPages: [Int],
        importedAt: Date
    ) {
        self.id = id
        self.sourcePath = sourcePath
        self.title = title
        self.sourceType = sourceType
        self.chunkCount = chunkCount
        self.lowQualityPages = lowQualityPages
        self.importedAt = importedAt
    }
}

public enum ReparseJobStatus: String, Sendable, Equatable, Codable {
    case queued
    case running
    case completed
    case failed
}

public struct ReparseJob: Identifiable, Sendable, Equatable, Codable {
    public let id: UUID
    public let documentID: UUID
    public let documentTitle: String
    public let sourcePath: String
    public let pageIndices: [Int]
    public let createdAt: Date
    public var status: ReparseJobStatus
    public var progress: Double
    public var message: String?

    public init(
        id: UUID = UUID(),
        documentID: UUID,
        documentTitle: String,
        sourcePath: String,
        pageIndices: [Int],
        createdAt: Date = Date(),
        status: ReparseJobStatus,
        progress: Double,
        message: String? = nil
    ) {
        self.id = id
        self.documentID = documentID
        self.documentTitle = documentTitle
        self.sourcePath = sourcePath
        self.pageIndices = pageIndices
        self.createdAt = createdAt
        self.status = status
        self.progress = progress
        self.message = message
    }
}
