import Domain
import Foundation
import TelemetryKit

public actor LowQualityReparseQueue {
    private var jobs: [UUID: ReparseJob] = [:]
    private var orderedJobIDs: [UUID] = []
    private var continuations: [UUID: AsyncStream<[ReparseJob]>.Continuation] = [:]

    private let reparser: LowQualityPageReparsing
    private let documentStore: any ImportedDocumentStore
    private let telemetry: Telemetry

    public init(
        reparser: LowQualityPageReparsing,
        documentStore: any ImportedDocumentStore,
        telemetry: Telemetry = ConsoleTelemetry()
    ) {
        self.reparser = reparser
        self.documentStore = documentStore
        self.telemetry = telemetry
    }

    public func currentJobs() -> [ReparseJob] {
        orderedJobIDs.compactMap { jobs[$0] }
    }

    public func subscribe() -> AsyncStream<[ReparseJob]> {
        let token = UUID()
        return AsyncStream { continuation in
            continuations[token] = continuation
            continuation.onTermination = { [weak self] _ in
                Task { await self?.removeContinuation(token) }
            }
            continuation.yield(orderedJobIDs.compactMap { jobs[$0] })
        }
    }

    public func enqueue(document: ImportedDocumentRecord) -> Bool {
        let pages = Array(Set(document.lowQualityPages)).sorted()
        guard !pages.isEmpty else { return false }

        let hasActiveJob = jobs.values.contains { existing in
            existing.documentID == document.id &&
            (existing.status == .queued || existing.status == .running)
        }
        if hasActiveJob {
            telemetry.warning("Skipped duplicate reparse enqueue for \(document.title)")
            return false
        }

        let job = ReparseJob(
            documentID: document.id,
            documentTitle: document.title,
            sourcePath: document.sourcePath,
            pageIndices: pages,
            status: .queued,
            progress: 0,
            message: "Queued"
        )

        jobs[job.id] = job
        orderedJobIDs.append(job.id)
        broadcast()

        Task {
            await process(jobID: job.id, document: document)
        }

        return true
    }

    private func process(jobID: UUID, document: ImportedDocumentRecord) async {
        update(jobID: jobID, status: .running, progress: 0.2, message: "Re-parsing PDF")

        do {
            let resolvedPages = try await reparser.reparse(document: document, pages: document.lowQualityPages)

            let remaining = document.lowQualityPages.filter { !resolvedPages.contains($0) }
            let sections = try await documentStore.sections(for: document.id)
            let updatedRecord = ImportedDocumentRecord(
                id: document.id,
                sourcePath: document.sourcePath,
                title: document.title,
                sourceType: document.sourceType,
                chunkCount: document.chunkCount,
                lowQualityPages: remaining,
                importedAt: Date()
            )

            try await documentStore.upsertDocument(updatedRecord, sections: sections)

            let message = "Resolved \(resolvedPages.count), remaining \(remaining.count)"
            update(jobID: jobID, status: .completed, progress: 1.0, message: message)
            telemetry.info("Low-quality reparse job completed: \(document.title). \(message)")
        } catch {
            update(jobID: jobID, status: .failed, progress: 1.0, message: error.localizedDescription)
            telemetry.error("Low-quality reparse failed: \(document.title), error=\(error.localizedDescription)")
        }
    }

    private func update(jobID: UUID, status: ReparseJobStatus, progress: Double, message: String?) {
        guard var job = jobs[jobID] else { return }
        job.status = status
        job.progress = max(0, min(progress, 1))
        job.message = message
        jobs[jobID] = job
        broadcast()
    }

    private func broadcast() {
        let snapshot = orderedJobIDs.compactMap { jobs[$0] }
        for continuation in continuations.values {
            continuation.yield(snapshot)
        }
    }

    private func removeContinuation(_ token: UUID) {
        continuations[token] = nil
    }
}
