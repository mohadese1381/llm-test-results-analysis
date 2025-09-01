# FailTrace  

**Leveraging Large Language Models for Automated Test Results Analysis**  

[![PyPI version](https://badge.fury.io/py/failtrace.svg)](https://pypi.org/project/failtrace/)  
[![Python Version](https://img.shields.io/pypi/pyversions/failtrace)](https://www.python.org/)  

---

## 🌍 Overview  

FailTrace helps developers and QA engineers **analyze automated test results** with **Large Language Models (LLMs)**.  
It builds **dependency graphs**, maps them with test execution logs, and generates **interactive HTML reports** with insights into failures.  

---

## ✨ Features  

- Supports **Python, Java, C#**  
- Dependency graph visualization (PyVis + NetworkX)  
- Test log parsing (Pytest, JSON, TRX, …)  
- Interactive reports (`HTML + CSS + JS`)  
- Dry-run mode (no API calls)  
- CLI-first design for CI/CD  

---

## 📦 Installation  

```bash
pip install failtrace
````

---

## ⚡ Quickstart

Run the **full pipeline**:

```bash
python -m failtrace full -p ./your-source-code -l ./your-test-results.xml --open-report
```

Run in **quick mode** (reuse cached graph):

```bash
failtrace quick -p ./src -l ./results.json
```

---

## 📜 License

Licensed under the [MIT License](https://opensource.org/licenses/MIT).

---

## 👩‍💻 Author

[**Mohadese Akhoondy**](mailto:m.akhoondy1381@gmail.com)

```
