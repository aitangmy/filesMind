import Domain
import Foundation
import TelemetryKit
#if canImport(PDFKit)
import PDFKit
#endif

public actor DefaultDocumentParser: DocumentParsing {
    private let router: PipelineRouter
    private let telemetry: Telemetry
    private let maxChunkCharacters: Int

    public init(
        router: PipelineRouter,
        telemetry: Telemetry = ConsoleTelemetry(),
        maxChunkCharacters: Int = 1200
    ) {
        self.router = router
        self.telemetry = telemetry
        self.maxChunkCharacters = max(200, maxChunkCharacters)
    }

    public func parse(fileURL: URL) async throws -> ParsedDocument {
        let ext = fileURL.pathExtension.lowercased()
        switch ext {
        case "md", "markdown", "txt":
            return try parseMarkdown(fileURL: fileURL)
        case "pdf":
            return try await parsePDF(fileURL: fileURL)
        default:
            throw FilesMindError.notSupported("Unsupported file type: .\(ext)")
        }
    }

    private func parseMarkdown(fileURL: URL) throws -> ParsedDocument {
        let raw = try readText(fileURL: fileURL)
        let normalized = normalize(raw)

        let title = firstHeading(in: normalized) ?? fileURL.deletingPathExtension().lastPathComponent
        let segments = normalized
            .components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        var chunks: [Chunk] = []
        var ordinal = 0

        for segment in segments {
            for piece in split(segment, limit: maxChunkCharacters) {
                chunks.append(Chunk(documentID: UUID(), ordinal: ordinal, text: piece))
                ordinal += 1
            }
        }

        if chunks.isEmpty {
            let fallback = normalized.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !fallback.isEmpty else {
                throw FilesMindError.validationFailed("Empty markdown document")
            }
            chunks = [Chunk(documentID: UUID(), ordinal: 0, text: fallback)]
        }

        let documentID = UUID()
        let normalizedChunks = chunks.enumerated().map { index, chunk in
            Chunk(documentID: documentID, ordinal: index, text: chunk.text)
        }

        telemetry.info("Markdown parsed: \(fileURL.lastPathComponent), chunks=\(normalizedChunks.count)")

        return ParsedDocument(
            documentID: documentID,
            sourceURL: fileURL,
            title: title,
            sourceType: .markdown,
            chunks: normalizedChunks,
            fallbackPageCount: 0
        )
    }

    private func parsePDF(fileURL: URL) async throws -> ParsedDocument {
#if canImport(PDFKit)
        guard let pdf = PDFDocument(url: fileURL) else {
            throw FilesMindError.validationFailed("Unable to open PDF")
        }

        var pageTexts: [String] = []
        var assessments: [ParsePageAssessment] = []

        for pageIndex in 0..<pdf.pageCount {
            let text = (pdf.page(at: pageIndex)?.string ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)

            let score: Double
            if text.count > 240 {
                score = 0.92
            } else if text.count > 80 {
                score = 0.74
            } else {
                score = 0.45
            }

            assessments.append(ParsePageAssessment(pageIndex: pageIndex, qualityScore: score))
            if !text.isEmpty {
                pageTexts.append(text)
            }
        }

        if pageTexts.isEmpty {
            throw FilesMindError.validationFailed("PDF has no extractable text")
        }

        let decisions = await router.route(assessments: assessments, vlmFallbackThreshold: 0.65)
        let fallbackPageCount = decisions.filter(\.requiresVLMFallback).count
        if fallbackPageCount > 0 {
            telemetry.warning("PDF low-quality pages requiring VLM fallback: \(fallbackPageCount)")
        }

        let documentID = UUID()
        var chunks: [Chunk] = []
        var ordinal = 0

        for pageText in pageTexts {
            for piece in split(pageText, limit: maxChunkCharacters) {
                chunks.append(Chunk(documentID: documentID, ordinal: ordinal, text: piece))
                ordinal += 1
            }
        }

        telemetry.info("PDF parsed: \(fileURL.lastPathComponent), chunks=\(chunks.count)")

        return ParsedDocument(
            documentID: documentID,
            sourceURL: fileURL,
            title: fileURL.deletingPathExtension().lastPathComponent,
            sourceType: .pdf,
            chunks: chunks,
            fallbackPageCount: fallbackPageCount
        )
#else
        throw FilesMindError.notSupported("PDF parsing not available on this build")
#endif
    }

    private func readText(fileURL: URL) throws -> String {
        if let text = try? String(contentsOf: fileURL, encoding: .utf8) {
            return text
        }
        let data = try Data(contentsOf: fileURL)
        guard let text = String(data: data, encoding: .utf8) else {
            throw FilesMindError.validationFailed("Unsupported text encoding")
        }
        return text
    }

    private func normalize(_ text: String) -> String {
        text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
    }

    private func firstHeading(in text: String) -> String? {
        for line in text.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.hasPrefix("#") {
                return trimmed.trimmingCharacters(in: CharacterSet(charactersIn: "# "))
            }
        }
        return nil
    }

    private func split(_ text: String, limit: Int) -> [String] {
        guard text.count > limit else {
            return [text]
        }

        var pieces: [String] = []
        var current = ""

        for token in text.split(separator: " ", omittingEmptySubsequences: true) {
            let candidate = current.isEmpty ? String(token) : current + " " + token
            if candidate.count > limit {
                if !current.isEmpty {
                    pieces.append(current)
                }
                current = String(token)
            } else {
                current = candidate
            }
        }

        if !current.isEmpty {
            pieces.append(current)
        }

        return pieces.isEmpty ? [text] : pieces
    }
}
