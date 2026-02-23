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
            }

            if model.searchResults.isEmpty {
                Text("No results to display.")
                    .font(.system(size: DesignTypography.body))
                    .foregroundStyle(.secondary)
            } else {
                List(model.searchResults, id: \.chunk.id) { ranked in
                    SearchResultRow(ranked: ranked)
                }
                .listStyle(.inset)
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

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSpacing.x1) {
            HStack {
                Text("Score \(String(format: "%.3f", ranked.score))")
                    .font(.system(size: DesignTypography.caption, weight: .semibold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
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
}
