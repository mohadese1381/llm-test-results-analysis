from pathlib import Path
import networkx as nx
from .base import GraphBuilder
from .plugins import register
from .python_graph import extract_python_graph

@register("python")
class PythonGraphBuilder(GraphBuilder):
    def build_graph(self, project_path: Path) -> nx.DiGraph:
        """
        Use the project-path-based CST extractor to build the Python graph.
        extract_python_graph returns a NetworkX DiGraph.
        """
        graph = extract_python_graph(str(project_path))
        return graph