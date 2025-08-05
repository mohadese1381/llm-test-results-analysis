from .detector import detect_language
from .python_graph import extract_python_graph

def build_graph(project_path: str) -> dict:
    lang = detect_language(project_path)

    if lang == "python":
        return extract_python_graph(project_path)
    elif lang == "java":
        raise NotImplementedError("Java support coming soon.")
    elif lang == "csharp":
        raise NotImplementedError("C# support coming soon.")
    else:
        raise ValueError("Unsupported language.")
