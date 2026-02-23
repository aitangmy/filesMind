import AppCore
import AppKit
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
    var focusedGraphNodeID: UUID?

    var searchQuery = ""
    var searchResults: [RankedChunk] = []
    var searchStatus = "Type keywords to search indexed chunks."
    var isSearching = false

    var importedDocuments: [ImportedDocumentRecord] = []
    var selectedDocumentID: UUID?
    var selectedDocumentSections: [ParsedSection] = []
    var selectedChunkPreview: String?
    var reparseJobs: [ReparseJob] = []

    var lastError: String?

    private let graphBoundary = Rect(x: -800, y: -800, width: 10000, height: 10000)
    private var graphIndex: QuadTreeIndex
    private var sectionNodeIDs: [UUID: UUID] = [:]

    private var queueObservationTask: Task<Void, Never>?
    private var reparseObservationTask: Task<Void, Never>?
    private var started = false

    init(container: AppContainer) {
        self.container = container
        self.graphIndex = QuadTreeIndex(boundary: graphBoundary, capacity: 24)

        let placeholderNodes = DemoGraphFactory.makePlaceholderNodes()
        self.graphNodes = placeholderNodes
        for node in placeholderNodes {
            graphIndex.insert(node)
        }
    }

    var selectedDocument: ImportedDocumentRecord? {
        guard let selectedDocumentID else { return nil }
        return importedDocuments.first(where: { $0.id == selectedDocumentID })
    }

    var selectedDocumentReparseJob: ReparseJob? {
        guard let selectedDocumentID else { return nil }
        return reparseJobs
            .filter { $0.documentID == selectedDocumentID }
            .sorted(by: { $0.createdAt > $1.createdAt })
            .first
    }

    var reparseComparison: ReparseComparison? {
        guard let doc = selectedDocument, let job = selectedDocumentReparseJob else { return nil }
        let beforeCount = max(job.pageIndices.count, doc.lowQualityPages.count)
        let afterCount = doc.lowQualityPages.count
        let resolvedCount = max(0, beforeCount - afterCount)
        let resolvedRatio = beforeCount > 0 ? Double(resolvedCount) / Double(beforeCount) : 0

        return ReparseComparison(
            status: job.status,
            beforeCount: beforeCount,
            afterCount: afterCount,
            resolvedCount: resolvedCount,
            resolvedRatio: resolvedRatio,
            progress: job.progress,
            updatedAt: job.createdAt,
            message: job.message
        )
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
                await self.reloadImportedDocuments()
            }
        }

        reparseObservationTask = Task { [weak self] in
            guard let self else { return }
            let stream = await self.container.lowQualityReparseQueue.subscribe()
            for await jobs in stream {
                self.reparseJobs = jobs
                await self.reloadImportedDocuments()
            }
        }

        Task {
            await self.reloadImportedDocuments()
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

    func selectImportedDocument(_ document: ImportedDocumentRecord) {
        selectedDocumentID = document.id
        selectedChunkPreview = nil

        Task {
            await loadSections(for: document.id)
            focusFirstSectionIfNeeded()
        }
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

    func selectSearchResult(_ ranked: RankedChunk) {
        let chunk = ranked.chunk
        selectedChunkPreview = chunk.text

        if selectedDocumentID != chunk.documentID {
            selectedDocumentID = chunk.documentID
        }

        Task {
            await loadSections(for: chunk.documentID)
            if let matchedSection = bestSection(forChunkOrdinal: chunk.ordinal, in: selectedDocumentSections) {
                focusedGraphNodeID = sectionNodeIDs[matchedSection.id]
                searchStatus = "Focused \(matchedSection.title) (chunk #\(chunk.ordinal))."
            } else {
                focusedGraphNodeID = nil
                searchStatus = "Focused chunk #\(chunk.ordinal), no section mapping."
            }
        }
    }

    func requestReparseLowQualityPages() {
        guard let doc = selectedDocument, !doc.lowQualityPages.isEmpty else { return }
        Task {
            await container.lowQualityReparseQueue.enqueue(document: doc)
        }
        let pageList = doc.lowQualityPages.map { String($0 + 1) }.joined(separator: ", ")
        searchStatus = "Re-parse queued for pages [\(pageList)]."
    }

    private func reloadImportedDocuments() async {
        guard let store = container.documentStore else {
            importedDocuments = []
            selectedDocumentSections = []
            selectedDocumentID = nil
            rebuildGraph(documents: [], sectionsMap: [:])
            return
        }

        do {
            let docs = try await store.recentDocuments(limit: 80)
            importedDocuments = docs

            var sectionsMap: [UUID: [ParsedSection]] = [:]
            for doc in docs {
                sectionsMap[doc.id] = try await store.sections(for: doc.id)
            }
            rebuildGraph(documents: docs, sectionsMap: sectionsMap)

            if let selectedDocumentID, docs.contains(where: { $0.id == selectedDocumentID }) {
                selectedDocumentSections = sectionsMap[selectedDocumentID] ?? []
                focusFirstSectionIfNeeded()
            } else if let first = docs.first {
                selectedDocumentID = first.id
                selectedDocumentSections = sectionsMap[first.id] ?? []
                focusFirstSectionIfNeeded()
            } else {
                selectedDocumentSections = []
                focusedGraphNodeID = nil
            }
        } catch {
            lastError = error.localizedDescription
        }
    }

    private func loadSections(for documentID: UUID) async {
        guard let store = container.documentStore else {
            selectedDocumentSections = []
            return
        }

        do {
            selectedDocumentSections = try await store.sections(for: documentID)
        } catch {
            lastError = error.localizedDescription
            selectedDocumentSections = []
        }
    }

    private func focusFirstSectionIfNeeded() {
        if let first = selectedDocumentSections.first {
            focusedGraphNodeID = sectionNodeIDs[first.id]
        } else {
            focusedGraphNodeID = nil
        }
    }

    private func bestSection(forChunkOrdinal ordinal: Int, in sections: [ParsedSection]) -> ParsedSection? {
        sections
            .sorted(by: { $0.chunkStartOrdinal < $1.chunkStartOrdinal })
            .last(where: { $0.chunkStartOrdinal <= ordinal })
    }

    private func rebuildGraph(documents: [ImportedDocumentRecord], sectionsMap: [UUID: [ParsedSection]]) {
        sectionNodeIDs = [:]

        if documents.isEmpty {
            let placeholders = DemoGraphFactory.makePlaceholderNodes()
            graphNodes = placeholders
            graphIndex = QuadTreeIndex(boundary: graphBoundary, capacity: 24)
            for node in placeholders {
                graphIndex.insert(node)
            }
            return
        }

        var newNodes: [GraphNode] = []

        for (docIndex, document) in documents.enumerated() {
            let baseY = Double(docIndex) * 300 + 80
            let qualityBadge = document.lowQualityPages.isEmpty ? "Clean" : "LQ \(document.lowQualityPages.count)"

            let rootNode = GraphNode(
                title: "\(document.title) • \(qualityBadge)",
                rect: Rect(x: 70, y: baseY, width: 260, height: 62)
            )
            newNodes.append(rootNode)

            let sections = (sectionsMap[document.id] ?? []).sorted(by: { $0.chunkStartOrdinal < $1.chunkStartOrdinal })
            if sections.isEmpty {
                let orphanNode = GraphNode(
                    title: "(no outline)",
                    rect: Rect(x: 380, y: baseY + 80, width: 180, height: 52)
                )
                newNodes.append(orphanNode)
                continue
            }

            for (sectionIndex, section) in sections.enumerated() {
                let x = 380 + Double(max(0, section.level - 1)) * 220
                let y = baseY + 82 + Double(sectionIndex) * 72
                let sectionNode = GraphNode(
                    title: section.title,
                    rect: Rect(x: x, y: y, width: 210, height: 52)
                )
                newNodes.append(sectionNode)
                sectionNodeIDs[section.id] = sectionNode.id
            }
        }

        graphNodes = newNodes
        graphIndex = QuadTreeIndex(boundary: graphBoundary, capacity: 24)
        for node in newNodes {
            graphIndex.insert(node)
        }
    }
}

struct ReparseComparison: Sendable {
    let status: ReparseJobStatus
    let beforeCount: Int
    let afterCount: Int
    let resolvedCount: Int
    let resolvedRatio: Double
    let progress: Double
    let updatedAt: Date
    let message: String?
}

enum DemoGraphFactory {
    static func makePlaceholderNodes() -> [GraphNode] {
        [
            GraphNode(title: "Import a document", rect: Rect(x: 120, y: 120, width: 260, height: 66)),
            GraphNode(title: "Build local knowledge graph", rect: Rect(x: 430, y: 210, width: 280, height: 66)),
            GraphNode(title: "Run semantic search", rect: Rect(x: 780, y: 300, width: 240, height: 66))
        ]
    }
}
