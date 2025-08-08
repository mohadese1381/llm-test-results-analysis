import os
from typing import Literal

def detect_language(project_path: str) -> Literal["python", "java", "csharp", "unknown"]:
    extensions = set()
    for root, _, files in os.walk(project_path):
        for file in files:
            _, ext = os.path.splitext(file.lower())
            extensions.add(ext)

    if ".py" in extensions:
        return "python"
    elif ".java" in extensions:
        return "java"
    elif ".cs" in extensions:
        return "csharp"
    else:
        return "unknown"
