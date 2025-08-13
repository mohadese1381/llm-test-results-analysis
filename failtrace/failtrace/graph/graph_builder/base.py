from abc import ABC, abstractmethod
from pathlib import Path
import networkx as nx


class GraphBuilder(ABC):
    @abstractmethod
    def build_graph(self, project_path: Path) -> nx.DiGraph:
        """
        Parse the project at project_path and return a NetworkX directed graph.
        """
        pass
