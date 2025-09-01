# FailTrace  

**Leveraging Large Language Models for Automated Test Results Analysis**  

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)  
[![PyPI version](https://badge.fury.io/py/failtrace.svg)](https://pypi.org/project/failtrace/)  
[![Python Version](https://img.shields.io/pypi/pyversions/failtrace)](https://www.python.org/)  

---

## 🌍 Overview  

FailTrace is a modern tool that helps developers and QA engineers **analyze automated test results** using **Large Language Models (LLMs)**.  
It automatically builds **dependency graphs**, maps them with test execution logs, and generates **interactive HTML reports** with deep insights into failures.  

---

## ✨ Features  

- Multi-language support: **Python, Java, C#**  
- Dependency graph visualization (PyVis + NetworkX)  
- Test log parsing (Pytest, JSON, TRX, …)  
- Critical function/code extraction for failure root cause analysis  
- Structured LLM prompt generation  
- Interactive reports (`HTML + CSS + JS`)  
- Dry-run mode (preview without API calls)  
- CLI-first design for CI/CD integration
  
---

## 📦 Installation & Quickstart

Follow these steps to set up **FailTrace** inside an isolated virtual environment:

### 1️⃣ Create a new project folder
```bash
mkdir my-project && cd my-project
````

### 2️⃣ Create a virtual environment

```bash
python -m venv .venv
```

### 3️⃣ Activate the virtual environment

On **Windows**:

```bash
.\.venv\Scripts\activate
```

On **Linux / macOS**:

```bash
source .venv/bin/activate
```

### 4️⃣ Install FailTrace from PyPI

```bash
pip install failtrace
```

### 5️⃣ Run FailTrace

Run the **full pipeline** on your project source code and test results:

```bash
python -m failtrace full -p ./your-source-code -l ./your-test-results.xml --open-report
```

---

## ⚡ CLI Usage

FailTrace provides multiple commands:

* **Full pipeline (from scratch)**:

```bash
failtrace full -p ./src -l ./results.xml --open-report
```

* **Quick mode (reuse cached graph, retag with new logs)**:

```bash
failtrace quick -p ./src -l ./results.json
```

* **Dry run (build final LLM prompt without API call)**:

```bash
failtrace full -p ./src -l ./results.xml --dry-run
```

---

## 📂 Output Structure

When you run FailTrace, it generates:

* **`report/`** – User-facing reports (HTML, CSS, JS).
* **`output/`** – Internal analysis artifacts (summary, prompts, critical paths).
* **`lib/`** – Internal library assets (hidden from end-users).

---

## 🛠 Development Setup

Clone the repository and install dependencies locally:

```bash
git clone https://github.com/your-username/failtrace.git
cd failtrace
poetry install
```

Run tests:

```bash
pytest
```

---

## 🤝 Contributing

Contributions are always welcome to improve **FailTrace**, whether it’s fixing bugs, enhancing documentation, or adding new features.  
To get started, fork the repository, create a new branch, and set up a virtual environment with `pip install -e ".[dev]"`.  
Please ensure that tests pass locally by running `pytest` before submitting your work.  
Use clear commit messages and keep pull requests focused and concise for easier review.  
When ready, push your branch and open a Pull Request—we’ll be happy to review it!

---

## 📜 License

Licensed under the [MIT License](LICENSE)

---

## 👩‍💻 Author

[**Mohadese Akhoondy**](mailto:m.akhoondy1381@gmail.com)  

---
