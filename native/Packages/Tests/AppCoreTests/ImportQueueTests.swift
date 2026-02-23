import AppCore
import Domain
import Foundation
import Testing

@Test("ImportQueue should move job to indexed state")
func importQueueShouldEventuallyIndexJob() async {
    let queue = ImportQueue(importer: MockDocumentImporter())
    let fileURL = URL(fileURLWithPath: "/tmp/sample.md")

    await queue.enqueue(fileURLs: [fileURL])

    try? await Task.sleep(for: .milliseconds(700))

    let jobs = await queue.currentJobs()
    #expect(jobs.count == 1)

    guard let job = jobs.first else { return }
    #expect(job.status == .indexed)
    #expect(job.progress == 1.0)
}

private actor MockDocumentImporter: DocumentImporting {
    func importDocument(at fileURL: URL) async throws -> ParsedDocument {
        let docID = UUID()
        let chunk = Chunk(documentID: docID, ordinal: 0, text: "sample text")
        return ParsedDocument(
            documentID: docID,
            sourceURL: fileURL,
            title: fileURL.lastPathComponent,
            sourceType: .markdown,
            chunks: [chunk]
        )
    }
}

@Test("ImportQueue should mark job failed when importer throws")
func importQueueShouldMarkFailed() async {
    let queue = ImportQueue(importer: FailingDocumentImporter())
    let fileURL = URL(fileURLWithPath: "/tmp/fail.md")

    await queue.enqueue(fileURLs: [fileURL])

    try? await Task.sleep(for: .milliseconds(200))

    let jobs = await queue.currentJobs()
    #expect(jobs.count == 1)
    guard let job = jobs.first else { return }
    #expect(job.status == .failed)
}

private actor FailingDocumentImporter: DocumentImporting {
    func importDocument(at fileURL: URL) async throws -> ParsedDocument {
        throw FilesMindError.validationFailed("mock import error")
    }
}
