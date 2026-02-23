import AppCore
import AppKit
import DesignSystem
import Domain
import Foundation
import GraphEngine
import Observation
import SearchKit

@MainActor
@Observable
final class AppModel {
    let container: AppContainer

    var workspaceID = WorkspaceID("default-workspace")
    var workspaceURL: URL?
    var workspaceStatus = "No workspace selected"
    var importJobs: [ImportJob] = []
    var graphNodes: [GraphNode] = []
    var searchQuery = ""
    var searchResults: [RankedChunk] = []
    var searchStatus = "Type keywords to search indexed chunks."
    var isSearching = false
    var lastError: String?

    private let graphIndex: QuadTreeIndex
    private var queueObservationTask: Task<Void, Never>?
    private var started = false

    init(container: AppContainer) {
        self.container = container
        self.graphNodes = DemoGraphFactory.makeNodes(count: 250)
        let boundary = Rect(x: -500, y: -500, width: 6000, height: 6000)
        self.graphIndex = QuadTreeIndex(boundary: boundary, capacity: 24)
        for node in graphNodes {
            graphIndex.insert(node)
        }
    }

    func start() {
        guard !started else { return }
        started = true

        queueObservationTask = Task { [weak self] in
            guard let self else { return }
            let useCase = ObserveImportQueueUseCase(queue: self.container.importQueue)
            let stream = await useCase.execute()
            for await jobs in stream {
                self.importJobs = jobs
            }
        }
    }

    func chooseWorkspace() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Select"
        panel.message = "Choose your filesMind workspace folder"

        guard panel.runModal() == .OK, let url = panel.url else {
            return
        }

        workspaceStatus = "Authorizing \(url.lastPathComponent)..."
        lastError = nil

        Task {
            do {
                let useCase = SelectWorkspaceUseCase(bookmarkManager: container.bookmarkManager)
                let authorization = try await useCase.execute(workspaceID: workspaceID, directoryURL: url)
                workspaceURL = authorization.directoryURL
                workspaceStatus = "Workspace: \(authorization.directoryURL.lastPathComponent)"
            } catch {
                workspaceStatus = "Workspace authorization failed"
                lastError = error.localizedDescription
            }
        }
    }

    func chooseAndEnqueueImports() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = []
        panel.prompt = "Import"
        panel.message = "Select Markdown or PDF files"

        guard panel.runModal() == .OK else {
            return
        }

        let urls = panel.urls
        guard !urls.isEmpty else { return }

        Task {
            let useCase = EnqueueImportUseCase(queue: container.importQueue)
            await useCase.execute(fileURLs: urls)
        }
    }

    func visibleGraphNodes(in viewport: Rect) -> [GraphNode] {
        graphIndex.visibleNodes(in: viewport)
    }

    func runSearch() {
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else {
            searchResults = []
            searchStatus = "Type keywords to search indexed chunks."
            return
        }

        isSearching = true
        searchStatus = "Searching..."
        lastError = nil

        Task {
            do {
                let results = try await container.searchService.search(
                    keyword: query,
                    embedding: [],
                    limit: 30,
                    keywordWeight: 1.0,
                    vectorWeight: 0.0
                )
                searchResults = results
                searchStatus = "Found \(results.count) result(s)."
            } catch {
                searchResults = []
                searchStatus = "Search failed."
                lastError = error.localizedDescription
            }
            isSearching = false
        }
    }
}

enum DemoGraphFactory {
    static func makeNodes(count: Int) -> [GraphNode] {
        let width: Double = 140
        let height: Double = 56

        return (0..<count).map { index in
            let col = index % 20
            let row = index / 20
            let jitterX = Double((index * 13) % 11) * 1.7
            let jitterY = Double((index * 7) % 9) * 1.4
            return GraphNode(
                title: "Node \(index + 1)",
                rect: Rect(
                    x: Double(col) * 180 + jitterX,
                    y: Double(row) * 92 + jitterY,
                    width: width,
                    height: height
                )
            )
        }
    }
}
