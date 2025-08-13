from typing import Type, Dict
from .base import GraphBuilder

_registry: Dict[str, Type[GraphBuilder]] = {}


def register(lang: str):
    """Decorator to register a GraphBuilder implementation for a language."""

    def decorator(cls: Type[GraphBuilder]):
        _registry[lang.lower()] = cls
        return cls

    return decorator


def get_builder(lang: str) -> GraphBuilder:
    """Return an instance of the registered GraphBuilder for the given language."""
    try:
        builder_cls = _registry[lang.lower()]
    except KeyError:
        raise ValueError(f"No GraphBuilder registered for language '{lang}'")
    return builder_cls()


from .python_graph_builder import PythonGraphBuilder
from .java_graph_builder import JavaGraphBuilder
from .csharp_graph_builder import CSharpGraphBuilder
