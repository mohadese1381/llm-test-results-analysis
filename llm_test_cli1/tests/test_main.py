import sys
from pathlib import Path
from graph.graph_builder import build_graph
from utils.visualizer import visualize_graph

if len(sys.argv) != 3:
    print("Usage: python -m tests.test_csharp /path/to/csharp/project /path/to/output/graph.html")
    sys.exit(1)

project_path = sys.argv[1]
output_html = sys.argv[2]

# گراف را بساز
G = build_graph(project_path)

print("=== C# Graph Test ===")
print(f"Project: {Path(project_path).resolve()}")
print(f"➤ Graph built: {len(G.nodes())} nodes, {len(G.edges())} edges")

# چند نود و یال نمونۀ اول را چاپ کن
sample_nodes = list(G.nodes(data=True))[:10]
sample_edges = list(G.edges(data=True))[:10]

print("\n• Sample nodes:")
for node, attrs in sample_nodes:
    print(f"  - {node} → {attrs}")

print("\n• Sample edges:")
for u, v, attrs in sample_edges:
    print(f"  - {u} -> {v}  {attrs}")

# خروجی HTML تعاملی
visualize_graph(G, output_html)
print(f"\n[✓] Interactive graph written to {output_html}")
