import Domain
import GraphEngine
import Testing

@Test("QuadTree returns only visible nodes")
func visibleNodesAreFilteredByViewport() {
    let boundary = Rect(x: 0, y: 0, width: 1000, height: 1000)
    let index = QuadTreeIndex(boundary: boundary, capacity: 4)

    let visibleNode = GraphNode(title: "visible", rect: Rect(x: 100, y: 100, width: 20, height: 20))
    let hiddenNode = GraphNode(title: "hidden", rect: Rect(x: 800, y: 800, width: 20, height: 20))

    index.insert(visibleNode)
    index.insert(hiddenNode)

    let viewport = Rect(x: 0, y: 0, width: 300, height: 300)
    let hits = index.visibleNodes(in: viewport)

    #expect(hits.contains(where: { $0.id == visibleNode.id }))
    #expect(!hits.contains(where: { $0.id == hiddenNode.id }))
}
