import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from llm.summarizer import summarize_functions

def main():
    project_path = "C:/Users/Mohadese/VSCodeProjects/MathUtility"
    prompt_file = "output/llm_prompt.json"
    
    summarize_functions(project_path, prompt_file)

if __name__ == "__main__":
    main()
