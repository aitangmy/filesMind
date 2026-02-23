import Domain
import Foundation

public struct IndexedNode: Sendable, Equatable {
    public let node: GraphNode

    public init(node: GraphNode) {
        self.node = node
    }
}

public final class QuadTreeIndex: @unchecked Sendable {
    private final class Node {
        let boundary: Rect
        let capacity: Int
        var points: [IndexedNode]
        var children: [Node] = []

        init(boundary: Rect, capacity: Int) {
            self.boundary = boundary
            self.capacity = capacity
            self.points = []
        }

        func insert(_ point: IndexedNode) -> Bool {
            guard boundary.intersects(point.node.rect) else {
                return false
            }

            if points.count < capacity && children.isEmpty {
                points.append(point)
                return true
            }

            if children.isEmpty {
                subdivide()
            }

            for child in children {
                if child.insert(point) {
                    return true
                }
            }

            points.append(point)
            return true
        }

        func query(_ range: Rect, results: inout [IndexedNode]) {
            guard boundary.intersects(range) else {
                return
            }

            for point in points where point.node.rect.intersects(range) {
                results.append(point)
            }

            for child in children {
                child.query(range, results: &results)
            }
        }

        private func subdivide() {
            let halfWidth = boundary.width / 2
            let halfHeight = boundary.height / 2

            let nw = Rect(x: boundary.x, y: boundary.y, width: halfWidth, height: halfHeight)
            let ne = Rect(x: boundary.x + halfWidth, y: boundary.y, width: halfWidth, height: halfHeight)
            let sw = Rect(x: boundary.x, y: boundary.y + halfHeight, width: halfWidth, height: halfHeight)
            let se = Rect(x: boundary.x + halfWidth, y: boundary.y + halfHeight, width: halfWidth, height: halfHeight)

            children = [
                Node(boundary: nw, capacity: capacity),
                Node(boundary: ne, capacity: capacity),
                Node(boundary: sw, capacity: capacity),
                Node(boundary: se, capacity: capacity)
            ]
        }
    }

    private let root: Node

    public init(boundary: Rect, capacity: Int = 32) {
        self.root = Node(boundary: boundary, capacity: max(1, capacity))
    }

    public func insert(_ node: GraphNode) {
        _ = root.insert(IndexedNode(node: node))
    }

    public func visibleNodes(in viewport: Rect) -> [GraphNode] {
        var hits: [IndexedNode] = []
        root.query(viewport, results: &hits)

        var dedup: [UUID: GraphNode] = [:]
        for hit in hits {
            dedup[hit.node.id] = hit.node
        }
        return Array(dedup.values)
    }
}
