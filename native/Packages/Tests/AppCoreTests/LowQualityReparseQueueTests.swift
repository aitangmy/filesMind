import AppCore
import Domain
import Foundation
import Testing

@Test("LowQualityReparseQueue should update remaining low-quality pages")
func lowQualityReparseQueueShouldUpdateDocumentStore() async throws {
    let docID = UUID()
    let initialDoc = ImportedDocumentRecord(
        id: docID,
        sourcePath: "/tmp/sample.pdf",
        title: "sample",
        sourceType: .pdf,
        chunkCount: 12,
        lowQualityPages: [0, 2, 3],
        importedAt: Date()
    )

    let store = MockDocumentStore(document: initialDoc, sections: [
        ParsedSection(documentID: docID, level: 1, title: "Root", chunkStartOrdinal: 0)
    ])

    let queue = LowQualityReparseQueue(
        reparser: MockLowQualityReparser(resolvedPages: [0, 2]),
        documentStore: store
    )

    let didEnqueue = await queue.enqueue(document: initialDoc)
    #expect(didEnqueue == true)
    try? await Task.sleep(for: .milliseconds(350))

    let jobs = await queue.currentJobs()
    #expect(jobs.count == 1)
    #expect(jobs.first?.status == .completed)

    let recent = try await store.recentDocuments(limit: 10)
    #expect(recent.count == 1)
    #expect(recent.first?.lowQualityPages == [3])
}

@Test("LowQualityReparseQueue should reject duplicate active jobs")
func lowQualityReparseQueueShouldRejectDuplicateActiveJobs() async throws {
    let docID = UUID()
    let initialDoc = ImportedDocumentRecord(
        id: docID,
        sourcePath: "/tmp/duplicate.pdf",
        title: "duplicate",
        sourceType: .pdf,
        chunkCount: 8,
        lowQualityPages: [1, 4],
        importedAt: Date()
    )

    let store = MockDocumentStore(document: initialDoc, sections: [])
    let queue = LowQualityReparseQueue(
        reparser: MockLowQualityReparser(resolvedPages: [1]),
        documentStore: store
    )

    let first = await queue.enqueue(document: initialDoc)
    let second = await queue.enqueue(document: initialDoc)

    #expect(first == true)
    #expect(second == false)

    try? await Task.sleep(for: .milliseconds(350))
    let jobs = await queue.currentJobs().filter { $0.documentID == docID }
    #expect(jobs.count == 1)
}

private actor MockLowQualityReparser: LowQualityPageReparsing {
    private let resolvedPages: [Int]

    init(resolvedPages: [Int]) {
        self.resolvedPages = resolvedPages
    }

    func reparse(document: ImportedDocumentRecord, pages: [Int]) async throws -> [Int] {
        _ = document
        _ = pages
        try? await Task.sleep(for: .milliseconds(120))
        return resolvedPages
    }
}

private actor MockDocumentStore: ImportedDocumentStore {
    private var document: ImportedDocumentRecord
    private var sectionList: [ParsedSection]

    init(document: ImportedDocumentRecord, sections: [ParsedSection]) {
        self.document = document
        self.sectionList = sections
    }

    func upsertDocument(_ document: ImportedDocumentRecord, sections: [ParsedSection]) async throws {
        self.document = document
        self.sectionList = sections
    }

    func recentDocuments(limit: Int) async throws -> [ImportedDocumentRecord] {
        guard limit > 0 else { return [] }
        return [document]
    }

    func sections(for documentID: UUID) async throws -> [ParsedSection] {
        guard documentID == document.id else { return [] }
        return sectionList
    }
}
