from pathlib import Path
import networkx as nx
from .base import GraphBuilder
from .plugins import register
from .csharp_graph import extract_csharp_graph

@register("csharp")
class CSharpGraphBuilder(GraphBuilder):
    def build_graph(self, project_path: Path) -> nx.DiGraph:
        """
        Build the C# code graph from AST JSON produced by Roslyn.
        """
        return extract_csharp_graph(str(project_path))
