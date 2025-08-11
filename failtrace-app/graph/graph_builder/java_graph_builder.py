from pathlib import Path
import networkx as nx
from .base import GraphBuilder
from .plugins import register
from .java_graph import extract_java_graph

@register("java")
class JavaGraphBuilder(GraphBuilder):
    def build_graph(self, project_path: Path) -> nx.DiGraph:
        """
        Build the Java code graph from AST JSON produced by JavaParser.
        """
        return extract_java_graph(str(project_path))