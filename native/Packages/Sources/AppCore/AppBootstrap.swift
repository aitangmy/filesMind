import DocumentPipeline
import Domain
import GraphEngine
import InferenceKit
import ModelManager
import SearchKit
import SecurityKit
import StorageKit
import TelemetryKit
import Foundation

public struct AppContainer: Sendable {
    public let telemetry: Telemetry
    public let bookmarkManager: WorkspaceAuthorizationManaging
    public let chunkRepository: ChunkRepository & EmbeddingSearchRepository
    public let documentStore: (any ImportedDocumentStore)?
    public let searchService: HybridSearchService
    public let lowQualityReparseQueue: LowQualityReparseQueue
    public let pipelineRouter: PipelineRouter
    public let modelManager: ModelManaging
    public let cognitiveEngine: CognitiveEngine
    public let importQueue: ImportQueue

    public init(
        telemetry: Telemetry,
        bookmarkManager: WorkspaceAuthorizationManaging,
        chunkRepository: ChunkRepository & EmbeddingSearchRepository,
        documentStore: (any ImportedDocumentStore)?,
        searchService: HybridSearchService,
        lowQualityReparseQueue: LowQualityReparseQueue,
        pipelineRouter: PipelineRouter,
        modelManager: ModelManaging,
        cognitiveEngine: CognitiveEngine,
        importQueue: ImportQueue
    ) {
        self.telemetry = telemetry
        self.bookmarkManager = bookmarkManager
        self.chunkRepository = chunkRepository
        self.documentStore = documentStore
        self.searchService = searchService
        self.lowQualityReparseQueue = lowQualityReparseQueue
        self.pipelineRouter = pipelineRouter
        self.modelManager = modelManager
        self.cognitiveEngine = cognitiveEngine
        self.importQueue = importQueue
    }
}

public enum AppBootstrap {
    public static func makeDefault(installRoot: URL) -> AppContainer {
        let telemetry = ConsoleTelemetry()
        let bookmarkStore = UserDefaultsBookmarkStore()
        let bookmarkManager = SecurityScopedBookmarkManager(store: bookmarkStore, telemetry: telemetry)
        let chunkRepository: any ChunkRepository & EmbeddingSearchRepository
        let storageRoot = installRoot.deletingLastPathComponent().appendingPathComponent("Storage", isDirectory: true)
        let databaseURL = storageRoot.appendingPathComponent("filesmind.sqlite", isDirectory: false)
        if let repository = try? GRDBChunkRepository(databaseURL: databaseURL, telemetry: telemetry) {
            chunkRepository = repository
        } else {
            telemetry.warning("Falling back to InMemoryChunkRepository")
            chunkRepository = InMemoryChunkRepository(telemetry: telemetry)
        }
        let search = HybridSearchService(
            chunkRepository: chunkRepository,
            embeddingRepository: chunkRepository,
            telemetry: telemetry
        )
        let router = PipelineRouter(telemetry: telemetry)
        let parser = DefaultDocumentParser(router: router, telemetry: telemetry)
        let documentStore = chunkRepository as? any ImportedDocumentStore
        let importer = DocumentImportService(
            parser: parser,
            chunkRepository: chunkRepository,
            documentStore: documentStore,
            telemetry: telemetry
        )
        let lowQualityReparser = DefaultLowQualityPageReparser(parser: parser, telemetry: telemetry)
        let lowQualityReparseQueue = LowQualityReparseQueue(
            reparser: lowQualityReparser,
            documentStore: documentStore ?? InMemoryChunkRepository(telemetry: telemetry),
            telemetry: telemetry
        )

        let catalog = StaticModelCatalog(models: [])
        let validator = SHA256ArtifactValidator()
        let modelManager = DefaultModelManager(
            catalog: catalog,
            validator: validator,
            installRoot: installRoot,
            telemetry: telemetry
        )

        let engine = StubCognitiveEngine(telemetry: telemetry)
        let importQueue = ImportQueue(importer: importer, telemetry: telemetry)

        return AppContainer(
            telemetry: telemetry,
            bookmarkManager: bookmarkManager,
            chunkRepository: chunkRepository,
            documentStore: documentStore,
            searchService: search,
            lowQualityReparseQueue: lowQualityReparseQueue,
            pipelineRouter: router,
            modelManager: modelManager,
            cognitiveEngine: engine,
            importQueue: importQueue
        )
    }
}

public actor SelectWorkspaceUseCase {
    private let bookmarkManager: WorkspaceAuthorizationManaging

    public init(bookmarkManager: WorkspaceAuthorizationManaging) {
        self.bookmarkManager = bookmarkManager
    }

    public func execute(workspaceID: WorkspaceID, directoryURL: URL) async throws -> WorkspaceAuthorization {
        try await bookmarkManager.authorizeWorkspace(id: workspaceID, directoryURL: directoryURL)
    }
}
