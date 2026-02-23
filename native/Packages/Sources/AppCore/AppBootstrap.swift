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
    public let searchService: HybridSearchService
    public let pipelineRouter: PipelineRouter
    public let modelManager: ModelManaging
    public let cognitiveEngine: CognitiveEngine
    public let importQueue: ImportQueue

    public init(
        telemetry: Telemetry,
        bookmarkManager: WorkspaceAuthorizationManaging,
        chunkRepository: ChunkRepository & EmbeddingSearchRepository,
        searchService: HybridSearchService,
        pipelineRouter: PipelineRouter,
        modelManager: ModelManaging,
        cognitiveEngine: CognitiveEngine,
        importQueue: ImportQueue
    ) {
        self.telemetry = telemetry
        self.bookmarkManager = bookmarkManager
        self.chunkRepository = chunkRepository
        self.searchService = searchService
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
        let chunkRepository = InMemoryChunkRepository(telemetry: telemetry)
        let search = HybridSearchService(
            chunkRepository: chunkRepository,
            embeddingRepository: chunkRepository,
            telemetry: telemetry
        )
        let router = PipelineRouter(telemetry: telemetry)

        let catalog = StaticModelCatalog(models: [])
        let validator = SHA256ArtifactValidator()
        let modelManager = DefaultModelManager(
            catalog: catalog,
            validator: validator,
            installRoot: installRoot,
            telemetry: telemetry
        )

        let engine = StubCognitiveEngine(telemetry: telemetry)
        let importQueue = ImportQueue(telemetry: telemetry)

        return AppContainer(
            telemetry: telemetry,
            bookmarkManager: bookmarkManager,
            chunkRepository: chunkRepository,
            searchService: search,
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
