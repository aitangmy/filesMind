import DocumentPipeline
import Domain
import Foundation
import Testing

@Test("DefaultDocumentParser should parse markdown into chunks")
func parseMarkdownIntoChunks() async throws {
    let tempURL = FileManager.default.temporaryDirectory
        .appendingPathComponent("filesmind-markdown-\(UUID().uuidString).md", isDirectory: false)

    let markdown = """
    # Title

    Paragraph one.

    Paragraph two with more content.
    """

    try markdown.write(to: tempURL, atomically: true, encoding: .utf8)

    let parser = DefaultDocumentParser(router: PipelineRouter())
    let parsed = try await parser.parse(fileURL: tempURL)

    #expect(parsed.sourceType == .markdown)
    #expect(parsed.title == "Title")
    #expect(parsed.chunks.count >= 2)
}
