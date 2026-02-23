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
    var activePageFilter: Int?

    var importedDocuments: [ImportedDocumentRecord] = []
    var selectedDocumentID: UUID?
    var selectedDocumentSections: [ParsedSection] = []
    var selectedChunkPreview: String?
    var reparseJobs: [ReparseJob] = []
    var reparseDiffExpanded = false
    var reparseDiffScope: ReparseDiffScope = .remaining

    var lastError: String?

    private let graphBoundary = Rect(x: -800, y: -800, width: 10000, height: 10000)
    private var graphIndex: QuadTreeIndex
    private var sectionNodeIDs: [UUID: UUID] = [:]

    private var queueObservationTask: Task<Void, Never>?
    private var reparseObservationTask: Task<Void, Never>?
    private var scopedWorkspaceHandle: WorkspaceAccessHandle?
    private var started = false
    private var unfilteredSearchResults: [RankedChunk] = []

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
        let beforePages = Array(Set(job.pageIndices)).sorted()
        let afterPages = Array(Set(doc.lowQualityPages)).sorted()
        let resolvedPages = beforePages.filter { !Set(afterPages).contains($0) }
        let remainingPages = afterPages

        let beforeCount = max(beforePages.count, afterPages.count)
        let afterCount = afterPages.count
        let resolvedCount = max(0, beforeCount - afterCount)
        let resolvedRatio = beforeCount > 0 ? Double(resolvedCount) / Double(beforeCount) : 0

        return ReparseComparison(
            status: job.status,
            beforeCount: beforeCount,
            afterCount: afterCount,
            resolvedCount: resolvedCount,
            resolvedRatio: resolvedRatio,
            beforePages: beforePages,
            afterPages: afterPages,
            resolvedPages: resolvedPages,
            remainingPages: remainingPages,
            progress: job.progress,
            updatedAt: job.createdAt,
            message: job.message
        )
    }

    var reparseDiffPages: [Int] {
        guard let comparison = reparseComparison else { return [] }
        switch reparseDiffScope {
        case .resolved:
            return comparison.resolvedPages
        case .remaining:
            return comparison.remainingPages
        case .input:
            return comparison.beforePages
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
                await self.reloadImportedDocuments()
                self.synchronizeReparseInteractionState()
            }
        }

        reparseObservationTask = Task { [weak self] in
            guard let self else { return }
            let stream = await self.container.lowQualityReparseQueue.subscribe()
            for await jobs in stream {
                self.reparseJobs = jobs
                await self.reloadImportedDocuments()
                self.synchronizeReparseInteractionState()
            }
        }

        Task {
            await self.restoreWorkspaceIfAvailable()
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
                try await activateWorkspaceAccess(for: authorization)
                workspaceURL = authorization.directoryURL
                workspaceStatus = authorization.isStale
                    ? "Workspace: \(authorization.directoryURL.lastPathComponent) (refreshed)"
                    : "Workspace: \(authorization.directoryURL.lastPathComponent)"
            } catch {
                workspaceStatus = "Workspace authorization failed"
                lastError = error.localizedDescription
            }
        }
    }

    func chooseAndEnqueueImports() {
        guard workspaceURL != nil else {
            lastError = nil
            searchStatus = "Choose workspace first, then import files."
            return
        }

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

    private func restoreWorkspaceIfAvailable() async {
        do {
            let authorization = try await container.bookmarkManager.resolveAuthorization(id: workspaceID)
            try await activateWorkspaceAccess(for: authorization)
            workspaceURL = authorization.directoryURL
            workspaceStatus = authorization.isStale
                ? "Workspace: \(authorization.directoryURL.lastPathComponent) (bookmark refreshed)"
                : "Workspace: \(authorization.directoryURL.lastPathComponent)"
        } catch FilesMindError.notFound {
            workspaceStatus = "No workspace selected"
        } catch {
            workspaceStatus = "Workspace restore failed"
            lastError = error.localizedDescription
        }
    }

    private func activateWorkspaceAccess(for authorization: WorkspaceAuthorization) async throws {
        if let scopedWorkspaceHandle {
            await container.bookmarkManager.stopScopedAccess(scopedWorkspaceHandle)
            self.scopedWorkspaceHandle = nil
        }
        let handle = try await container.bookmarkManager.startScopedAccess(id: authorization.workspaceID)
        self.scopedWorkspaceHandle = handle
    }

    func visibleGraphNodes(in viewport: Rect) -> [GraphNode] {
        graphIndex.visibleNodes(in: viewport)
    }

    func selectImportedDocument(_ document: ImportedDocumentRecord) {
        selectedDocumentID = document.id
        selectedChunkPreview = nil
        activePageFilter = nil

        Task {
            await loadSections(for: document.id)
            focusFirstSectionIfNeeded()
            applySearchPageFilter()
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
                unfilteredSearchResults = results
                applySearchPageFilter()
            } catch {
                searchResults = []
                unfilteredSearchResults = []
                searchStatus = "Search failed."
                lastError = error.localizedDescription
            }
            isSearching = false
        }
    }

    func selectSearchResult(_ ranked: RankedChunk) {
        let chunk = ranked.chunk
        selectedChunkPreview = chunk.text
        activePageFilter = chunk.sourcePageIndex

        if selectedDocumentID != chunk.documentID {
            selectedDocumentID = chunk.documentID
        }

        Task {
            await loadSections(for: chunk.documentID)
            applySearchPageFilter()
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
            let enqueued = await container.lowQualityReparseQueue.enqueue(document: doc)
            if enqueued {
                let pageList = doc.lowQualityPages.map { String($0 + 1) }.joined(separator: ", ")
                searchStatus = "Re-parse queued for pages [\(pageList)]."
            } else {
                searchStatus = "Re-parse already in progress for this document."
            }
        }
    }

    func toggleReparseDiffExpanded() {
        reparseDiffExpanded.toggle()
    }

    func selectReparseDiffScope(_ scope: ReparseDiffScope) {
        reparseDiffScope = scope
        if let activePageFilter, !reparseDiffPages.contains(activePageFilter) {
            self.activePageFilter = nil
        }
        applySearchPageFilter()
    }

    func togglePageFilter(_ pageIndex: Int) {
        if activePageFilter == pageIndex {
            activePageFilter = nil
        } else {
            activePageFilter = pageIndex
        }
        applySearchPageFilter()
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
            synchronizeReparseInteractionState()
            applySearchPageFilter()
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

    private func applySearchPageFilter() {
        let filtered: [RankedChunk]
        if let page = activePageFilter {
            filtered = unfilteredSearchResults.filter { $0.chunk.sourcePageIndex == page }
        } else {
            filtered = unfilteredSearchResults
        }
        searchResults = filtered

        let baseCount = unfilteredSearchResults.count
        if let page = activePageFilter {
            searchStatus = "Filtered \(filtered.count)/\(baseCount) results for page \(page + 1)."
        } else if baseCount > 0 {
            searchStatus = "Found \(filtered.count) result(s)."
        } else if !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isSearching {
            searchStatus = "No results."
        }
    }

    private func synchronizeReparseInteractionState() {
        guard reparseComparison != nil else {
            reparseDiffExpanded = false
            activePageFilter = nil
            return
        }

        if let activePageFilter, !reparseDiffPages.contains(activePageFilter) {
            self.activePageFilter = nil
        }
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
    let beforePages: [Int]
    let afterPages: [Int]
    let resolvedPages: [Int]
    let remainingPages: [Int]
    let progress: Double
    let updatedAt: Date
    let message: String?
}

enum ReparseDiffScope: String, CaseIterable, Sendable {
    case resolved
    case remaining
    case input
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
