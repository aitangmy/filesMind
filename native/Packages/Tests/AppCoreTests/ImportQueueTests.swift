import AppCore
import Domain
import Foundation
import Testing

@Test("ImportQueue should move job to indexed state")
func importQueueShouldEventuallyIndexJob() async {
    let queue = ImportQueue()
    let fileURL = URL(fileURLWithPath: "/tmp/sample.md")

    await queue.enqueue(fileURLs: [fileURL])

    try? await Task.sleep(for: .milliseconds(700))

    let jobs = await queue.currentJobs()
    #expect(jobs.count == 1)

    guard let job = jobs.first else { return }
    #expect(job.status == .indexed)
    #expect(job.progress == 1.0)
}
