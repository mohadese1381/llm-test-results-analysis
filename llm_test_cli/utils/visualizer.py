from pyvis.network import Network
import networkx as nx
import os

def visualize_graph(graph: nx.DiGraph, output_file: str = "graph.html"):
    net = Network(height="800px", width="100%", directed=True, notebook=False)
    net.force_atlas_2based()  

    for node, attrs in graph.nodes(data=True):
        label = node
        title_lines = [
            f"<b>Node:</b> {node}",
            f"<b>File:</b> {attrs.get('file', 'N/A')}",
            f"<b>Line:</b> {attrs.get('start_line', '-')}",
        ]
        if attrs.get("is_test"):
            color = "orange"
            shape = "box"
        else:
            color = "lightblue"
            shape = "ellipse"

        status = attrs.get("test_status")
        if status == "failed":
            color = "red"
        elif status == "passed":
            color = "green"

        net.add_node(node, label=label, title="<br>".join(title_lines), color=color, shape=shape)

    for src, dst in graph.edges():
        net.add_edge(src, dst)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    net.write_html(output_file)
    print(f"[✓] Graph saved to {output_file}")
