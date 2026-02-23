import DesignSystem
import Domain
import SearchKit
import SwiftUI

struct WorkspaceShellView: View {
    @Bindable var model: AppModel

    var body: some View {
        NavigationSplitView {
            SidebarPane(model: model)
                .frame(minWidth: 250)
        } content: {
            ImportQueuePane(model: model)
                .frame(minWidth: 330)
        } detail: {
            MindMapCanvasPane(model: model)
                .frame(minWidth: 600)
        }
        .navigationTitle("filesMind")
    }
}

private struct SidebarPane: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x4) {
            Text("Workspace")
                .font(.system(size: DesignTypography.hero, weight: .semibold))

            Text(model.workspaceStatus)
                .font(.system(size: DesignTypography.body))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)

            if let workspaceURL = model.workspaceURL {
                Text(workspaceURL.path())
                    .font(.system(size: DesignTypography.caption, weight: .regular, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }

            if let lastError = model.lastError {
                Text(lastError)
                    .font(.system(size: DesignTypography.body))
                    .foregroundStyle(.red)
                    .lineLimit(3)
            }

            Divider()

            Button("Choose Workspace") {
                model.chooseWorkspace()
            }
            .buttonStyle(.borderedProminent)

            Button("Import Files") {
                model.chooseAndEnqueueImports()
            }
            .buttonStyle(.bordered)
            .disabled(model.workspaceURL == nil)

            if model.workspaceURL == nil {
                Text("Select a workspace first to enable document import.")
                    .font(.system(size: DesignTypography.caption))
                    .foregroundStyle(.secondary)
            }

            Divider()

            Text("Imported Documents")
                .font(.system(size: DesignTypography.title, weight: .semibold))

            if model.importedDocuments.isEmpty {
                Text("No imported documents yet.")
                    .font(.system(size: DesignTypography.body))
                    .foregroundStyle(.secondary)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                        ForEach(model.importedDocuments) { document in
                            ImportedDocumentRow(
                                document: document,
                                isSelected: document.id == model.selectedDocumentID
                            ) {
                                model.selectImportedDocument(document)
                            }
                        }
                    }
                }
                .frame(maxHeight: 220)
            }

            if !model.selectedDocumentSections.isEmpty {
                VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                    Text("Outline")
                        .font(.system(size: DesignTypography.title, weight: .semibold))
                    ForEach(model.selectedDocumentSections.prefix(10)) { section in
                        Text("\(String(repeating: "  ", count: max(0, section.level - 1)))• \(section.title)")
                            .font(.system(size: DesignTypography.caption, weight: .regular, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                .padding(DesignSpacing.x3)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: DesignCornerRadius.medium))
            }

            if let selectedDocument = model.selectedDocument, !selectedDocument.lowQualityPages.isEmpty {
                let pageList = selectedDocument.lowQualityPages.map { String($0 + 1) }.joined(separator: ", ")
                VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                    Text("PDF Quality")
                        .font(.system(size: DesignTypography.title, weight: .semibold))
                    Text("Low-quality pages: \(pageList)")
                        .font(.system(size: DesignTypography.caption, weight: .regular, design: .monospaced))
                        .foregroundStyle(.orange)
                    Button("Re-parse Low-quality Pages") {
                        model.requestReparseLowQualityPages()
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.selectedDocumentReparseJob?.status == .running)
                }
                .padding(DesignSpacing.x3)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: DesignCornerRadius.medium))

                if let comparison = model.reparseComparison {
                    ReparseComparisonCard(model: model, comparison: comparison)
                }
            }

            Spacer(minLength: DesignSpacing.x3)

            VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                Text("Aesthetic Baseline")
                    .font(.system(size: DesignTypography.title, weight: .medium))
                Text("Calm · Precision · Depth · Focus")
                    .font(.system(size: DesignTypography.body))
                    .foregroundStyle(.secondary)
            }
            .padding(DesignSpacing.x3)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: DesignCornerRadius.medium))
        }
        .padding(DesignSpacing.x4)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

private struct ImportedDocumentRow: View {
    let document: ImportedDocumentRecord
    let isSelected: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: DesignSpacing.x1) {
                HStack {
                    Text(document.title)
                        .font(.system(size: DesignTypography.body, weight: .medium))
                        .lineLimit(1)
                    Spacer(minLength: 8)
                    Text(document.sourceType.rawValue.uppercased())
                        .font(.system(size: DesignTypography.caption, weight: .semibold))
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: DesignSpacing.x2) {
                    Text("\(document.chunkCount) chunks")
                    if !document.lowQualityPages.isEmpty {
                        Text("fallback pages: \(document.lowQualityPages.count)")
                            .foregroundStyle(.orange)
                    }
                }
                .font(.system(size: DesignTypography.caption))
            }
            .padding(DesignSpacing.x2)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(backgroundStyle, in: RoundedRectangle(cornerRadius: DesignCornerRadius.small))
        }
        .buttonStyle(.plain)
    }

    private var backgroundStyle: Color {
        isSelected ? Color.accentColor.opacity(0.15) : Color(nsColor: .controlBackgroundColor)
    }
}

private func reparseStatusColor(_ status: ReparseJobStatus) -> Color {
    switch status {
    case .queued:
        return .gray
    case .running:
        return .orange
    case .completed:
        return .green
    case .failed:
        return .red
    }
}

private struct ReparseComparisonCard: View {
    @Bindable var model: AppModel
    let comparison: ReparseComparison

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x3) {
            HStack {
                Label("Reparse Comparison", systemImage: "waveform.path.ecg.rectangle")
                    .font(.system(size: DesignTypography.bodyLarge, weight: .semibold))
                Spacer(minLength: 8)
                Text(comparison.status.rawValue.uppercased())
                    .font(.system(size: DesignTypography.caption, weight: .semibold))
                    .foregroundStyle(reparseStatusColor(comparison.status))
            }

            HStack(spacing: DesignSpacing.x4) {
                metricBlock(value: "\(comparison.beforeCount)", label: "Before")
                metricBlock(value: "\(comparison.afterCount)", label: "After")
                metricBlock(value: "\(comparison.resolvedCount)", label: "Resolved")
                metricBlock(value: "\(Int((comparison.resolvedRatio * 100).rounded()))%", label: "Rate")
            }

            HStack(spacing: DesignSpacing.x2) {
                Image(systemName: "point.3.connected.trianglepath.dotted")
                    .foregroundStyle(.secondary)
                Text("Map synced")
                    .font(.system(size: DesignTypography.caption, weight: .medium))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 6)
                Text(comparison.updatedAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.system(size: DesignTypography.caption, weight: .regular, design: .monospaced))
                    .foregroundStyle(.secondary)
            }

            if comparison.status == .running || comparison.status == .queued {
                ProgressView(value: comparison.progress)
                    .tint(reparseStatusColor(comparison.status))
            }

            if let message = comparison.message, !message.isEmpty {
                Text(message)
                    .font(.system(size: DesignTypography.caption))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Button {
                withAnimation(.spring(response: DesignMotion.regular, dampingFraction: 0.9)) {
                    model.toggleReparseDiffExpanded()
                }
            } label: {
                HStack(spacing: DesignSpacing.x2) {
                    Image(systemName: model.reparseDiffExpanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 11, weight: .semibold))
                    Text("Page Diff")
                        .font(.system(size: DesignTypography.caption, weight: .semibold))
                    Spacer(minLength: 8)
                }
                .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)

            if model.reparseDiffExpanded {
                VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                    HStack(spacing: DesignSpacing.x1) {
                        ForEach(ReparseDiffScope.allCases, id: \.self) { scope in
                            Button {
                                model.selectReparseDiffScope(scope)
                            } label: {
                                Text(scopeTitle(scope))
                                    .font(.system(size: 11, weight: .semibold))
                                    .padding(.horizontal, DesignSpacing.x2)
                                    .padding(.vertical, DesignSpacing.x1)
                                    .background(scopeBackground(scope), in: Capsule())
                                    .overlay(
                                        Capsule()
                                            .strokeBorder(scopeBorder(scope), lineWidth: 1)
                                    )
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.bottom, DesignSpacing.x1)

                    if model.reparseDiffPages.isEmpty {
                        Text("No pages in this scope.")
                            .font(.system(size: DesignTypography.caption))
                            .foregroundStyle(.secondary)
                    } else {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: DesignSpacing.x1) {
                                ForEach(model.reparseDiffPages, id: \.self) { page in
                                    Button {
                                        model.togglePageFilter(page)
                                    } label: {
                                        Text("P\(page + 1)")
                                            .font(.system(size: 11, weight: .semibold, design: .rounded))
                                            .padding(.horizontal, DesignSpacing.x2)
                                            .padding(.vertical, DesignSpacing.x1)
                                            .background(pageChipBackground(page), in: Capsule())
                                            .overlay(
                                                Capsule()
                                                    .strokeBorder(pageChipBorder(page), lineWidth: 1)
                                            )
                                    }
                                    .buttonStyle(.plain)
                                    .help("Filter search results by page \(page + 1)")
                                }
                            }
                            .padding(.vertical, 1)
                        }
                    }

                    pageLine(
                        title: "Resolved",
                        pages: comparison.resolvedPages,
                        color: .green
                    )
                    pageLine(
                        title: "Remaining",
                        pages: comparison.remainingPages,
                        color: .orange
                    )
                    pageLine(
                        title: "Input",
                        pages: comparison.beforePages,
                        color: .secondary
                    )
                }
                .padding(DesignSpacing.x2)
                .background(Color.primary.opacity(0.03), in: RoundedRectangle(cornerRadius: DesignCornerRadius.small))
                .transition(.opacity.combined(with: .scale(scale: 0.98)))
            }
        }
        .padding(DesignSpacing.x3)
        .background {
            ZStack {
                RoundedRectangle(cornerRadius: DesignCornerRadius.medium)
                    .fill(.ultraThinMaterial)
                RoundedRectangle(cornerRadius: DesignCornerRadius.medium)
                    .fill(
                        LinearGradient(
                            colors: [
                                reparseStatusColor(comparison.status).opacity(0.12),
                                Color.cyan.opacity(0.08)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                RoundedRectangle(cornerRadius: DesignCornerRadius.medium)
                    .strokeBorder(
                        LinearGradient(
                            colors: [
                                reparseStatusColor(comparison.status).opacity(0.60),
                                Color.teal.opacity(0.45)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
            }
        }
    }

    private func scopeTitle(_ scope: ReparseDiffScope) -> String {
        switch scope {
        case .resolved:
            return "Resolved"
        case .remaining:
            return "Remaining"
        case .input:
            return "Input"
        }
    }

    private func scopeBackground(_ scope: ReparseDiffScope) -> Color {
        if model.reparseDiffScope == scope {
            return reparseStatusColor(comparison.status).opacity(0.18)
        }
        return Color.primary.opacity(0.04)
    }

    private func scopeBorder(_ scope: ReparseDiffScope) -> Color {
        if model.reparseDiffScope == scope {
            return reparseStatusColor(comparison.status).opacity(0.6)
        }
        return Color.primary.opacity(0.12)
    }

    private func pageChipBackground(_ page: Int) -> Color {
        if model.activePageFilter == page {
            return Color.accentColor.opacity(0.20)
        }
        return Color.primary.opacity(0.05)
    }

    private func pageChipBorder(_ page: Int) -> Color {
        if model.activePageFilter == page {
            return Color.accentColor.opacity(0.70)
        }
        return Color.primary.opacity(0.14)
    }

    private func metricBlock(value: String, label: String) -> some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x1) {
            Text(value)
                .font(.system(size: 20, weight: .semibold, design: .rounded))
                .foregroundStyle(.primary)
            Text(label)
                .font(.system(size: DesignTypography.caption, weight: .medium))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func pageLine(title: String, pages: [Int], color: Color) -> some View {
        let rendered = pages.isEmpty ? "none" : pages.map { String($0 + 1) }.joined(separator: ", ")
        return HStack(alignment: .top, spacing: DesignSpacing.x2) {
            Text(title)
                .font(.system(size: DesignTypography.caption, weight: .semibold))
                .foregroundStyle(color)
                .frame(width: 74, alignment: .leading)
            Text(rendered)
                .font(.system(size: DesignTypography.caption, weight: .regular, design: .monospaced))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }
}

private struct ImportQueuePane: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x3) {
            Text("Import Queue")
                .font(.system(size: DesignTypography.hero, weight: .semibold))

            Group {
                if model.importJobs.isEmpty {
                    VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                        Text("No jobs yet")
                            .font(.system(size: DesignTypography.bodyLarge, weight: .medium))
                        Text("Use \"Import Files\" to enqueue Markdown/PDF documents.")
                            .font(.system(size: DesignTypography.body))
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, DesignSpacing.x2)
                } else {
                    List(model.importJobs) { job in
                        ImportJobRow(job: job)
                    }
                    .listStyle(.inset)
                }
            }

            Divider()

            VStack(alignment: .leading, spacing: DesignSpacing.x2) {
                Text("Search")
                    .font(.system(size: DesignTypography.title, weight: .semibold))
                HStack(spacing: DesignSpacing.x2) {
                    TextField("Search indexed chunks", text: $model.searchQuery)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit {
                            model.runSearch()
                        }

                    Button {
                        model.runSearch()
                    } label: {
                        if model.isSearching {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Text("Run")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isSearching)
                }

                Text(model.searchStatus)
                    .font(.system(size: DesignTypography.caption))
                    .foregroundStyle(.secondary)

                if let page = model.activePageFilter {
                    HStack(spacing: DesignSpacing.x2) {
                        Label("Page filter: \(page + 1)", systemImage: "line.3.horizontal.decrease.circle")
                            .font(.system(size: DesignTypography.caption, weight: .medium))
                            .foregroundStyle(.secondary)
                        Button("Clear") {
                            model.togglePageFilter(page)
                        }
                        .buttonStyle(.borderless)
                        .font(.system(size: DesignTypography.caption, weight: .semibold))
                    }
                }
            }

            if model.searchResults.isEmpty {
                Text("No results to display.")
                    .font(.system(size: DesignTypography.body))
                    .foregroundStyle(.secondary)
            } else {
                List(model.searchResults, id: \.chunk.id) { ranked in
                    SearchResultRow(ranked: ranked) {
                        model.selectSearchResult(ranked)
                    }
                }
                .listStyle(.inset)
            }

            if let selectedChunkPreview = model.selectedChunkPreview {
                Divider()
                VStack(alignment: .leading, spacing: DesignSpacing.x1) {
                    Text("Focused Chunk")
                        .font(.system(size: DesignTypography.caption, weight: .semibold))
                    Text(selectedChunkPreview)
                        .font(.system(size: DesignTypography.body))
                        .lineLimit(5)
                        .textSelection(.enabled)
                }
                .padding(DesignSpacing.x2)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: DesignCornerRadius.small))
            }
        }
        .padding(DesignSpacing.x4)
        .background(Color(nsColor: .controlBackgroundColor))
    }
}

private struct ImportJobRow: View {
    let job: ImportJob

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x2) {
            HStack {
                Text(job.fileURL.lastPathComponent)
                    .font(.system(size: DesignTypography.bodyLarge, weight: .medium))
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(job.status.rawValue.capitalized)
                    .font(.system(size: DesignTypography.caption, weight: .semibold))
                    .foregroundStyle(statusColor)
                    .textCase(.uppercase)
            }

            ProgressView(value: job.progress)
                .tint(statusColor)

            if let message = job.message {
                Text(message)
                    .font(.system(size: DesignTypography.caption))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, DesignSpacing.x1)
    }

    private var statusColor: Color {
        switch job.status {
        case .queued:
            return .gray
        case .parsing:
            return .orange
        case .indexed:
            return .green
        case .failed:
            return .red
        }
    }
}

private struct SearchResultRow: View {
    let ranked: RankedChunk
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            VStack(alignment: .leading, spacing: DesignSpacing.x1) {
                HStack {
                    Text("Score \(String(format: "%.3f", ranked.score))")
                        .font(.system(size: DesignTypography.caption, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Spacer(minLength: 8)
                    if let page = ranked.chunk.sourcePageIndex {
                        Text("P\(page + 1)")
                            .font(.system(size: DesignTypography.caption, weight: .semibold, design: .rounded))
                            .foregroundStyle(.secondary)
                    }
                    Text("#\(ranked.chunk.ordinal)")
                        .font(.system(size: DesignTypography.caption, weight: .medium, design: .monospaced))
                        .foregroundStyle(.secondary)
                }

                Text(ranked.chunk.text)
                    .font(.system(size: DesignTypography.body))
                    .lineLimit(4)
                    .textSelection(.enabled)
            }
            .padding(.vertical, DesignSpacing.x1)
        }
        .buttonStyle(.plain)
    }
}
