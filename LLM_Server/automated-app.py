from flask import Flask, request, send_file, jsonify
from string import Template
import requests
import os
import time

app = Flask(__name__)

API_URL = "https://api.together.xyz/v1/chat/completions"
API_KEY = "490acbd83989f44751fa2f6ec07bf7b9f247e5f87fa5309983be9e6622aa43eb"

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

MODEL_NAME = "mistralai/Mixtral-8x7B-Instruct-v0.1"

HTML_TEMPLATE = Template(
    """
<!DOCTYPE html>
<html lang="fa">
<head>
    <meta charset="UTF-8">
    <title>🔍 تحلیل خودکار تست</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 30px;
            direction: rtl;
        }
        h1 {
            text-align: center;
            margin-bottom: 20px;
            color: #61dafb;
            font-size: 2.5em;
        }
        h2 {
            margin-bottom: 10px;
            color: #9cdcfe;
            font-size: 1.5em;
            border-bottom: 2px solid #333;
            padding-bottom: 5px;
        }
        .section {
            background: #2d2d2d;
            padding: 20px;
            margin: 20px auto;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.5);
            max-width: 900px;
        }
        .section strong {
            color: #4ec9b0;
        }
        pre {
            background: #262626;
            color: #dcdcdc;
            padding: 15px;
            border-radius: 6px;
            overflow-x: auto;
            white-space: pre-wrap;
            font-family: 'Consolas', 'Courier New', monospace;
            margin-top: 10px;
        }
        code {
            background: #333;
            padding: 2px 4px;
            border-radius: 4px;
            font-family: 'Consolas', 'Courier New', monospace;
        }
    </style>
</head>
<body>
    <h1>📄 تحلیل خودکار تست</h1>

    <div class="section">
        <h2>🧪 زبان پروژه</h2>
        <p>$language</p>
    </div>

    <div class="section">
        <h2>📤 خروجی اجرای تست</h2>
        <pre>$test_output</pre>
    </div>

    <div class="section">
        <h2>🧠 گزارش تحلیلی مدل</h2>
        <pre>$model_analysis</pre>
    </div>
</body>
</html>
"""
)

PROMPT_TEMPLATE = Template(
    """
You are an expert software QA analyst integrated into a test pipeline. Your role is to analyze the results of both unit tests and integration tests and generate detailed and actionable diagnostic reports for developers.

You will be provided with:

1. A set of test results (e.g., pass/fail status, stack traces, logs, assertions).
2. The related test definitions (including test names, input conditions, and expected behavior).
3. (Optional but helpful) Segments of the application source code or architecture context.

Your goal is to perform a root cause analysis of failed tests and produce a structured, professional report that includes:

- A categorized summary of all failed unit and integration tests.
- Likely root causes based on the failure context, code behavior, and integration points.
- Distinction between code-level issues vs. environment/configuration-related problems.
- References to relevant modules, methods, or interfaces where the fault likely originates.
- Suggestions for resolution, including:
  - Code-level fixes (e.g., null handling, type mismatch, logic error)
  - Integration/config fixes (e.g., API version mismatch, DB state issues)
  - Test design flaws (e.g., unrealistic mocks, timing issues)
- Clarify if the failure could be a false positive/negative or flaky behavior.

📌 Assumptions:
- The test framework and language may vary (JUnit, pytest, Mocha, etc.), so base your reasoning on the logic and semantics of testing, not syntax.
- Be objective, concise, and specific. Avoid generic advice.
- Your audience is a senior developer or tester who expects accurate, root-cause-level insights, not superficial summaries.

Your output must use one consistent simple HTML-like structure (do NOT change layout each time), including:

📄 Test Summary:
Total Tests: X | Failed: Y | Passed: Z

❌ Failed Test Cases:
[TestName]:
Type: [Unit | Integration]
Observed Failure: [Exception or message]
Root Cause Analysis: [Concise explanation]
Related Code/Module: [e.g., UserService.validate()]
Suggested Fix: [Actionable suggestion]

🧠 Insights:
[Optional: Pattern of failure, recurring module, dependency instability, etc.]

✅ Next Steps:
[List of prioritized actions the developer should take]

---------------------
Programming Language: $language

Test Output (CLI):
---------------------
$test_output

Test Code:
---------------------
$test_code

Source Code:
---------------------
$source_code
"""
)


def call_model(prompt: str) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 1000,
    }
    start = time.time()
    try:
        res = requests.post(API_URL, headers=HEADERS, json=payload, timeout=120)
        res.raise_for_status()
        content = res.json()["choices"][0]["message"]["content"]
        print(f"LLM latency: {time.time() - start:.2f}s")
        return content
    except requests.exceptions.RequestException as e:
        print("LLM error:", e)
        return f"Error connecting to llm : {str(e)}"


@app.route("/analyze_test_output", methods=["POST"])
def analyze_test_output():
    language = "unknown"
    test_output = ""
    test_code = ""
    source_code = ""

    try:
        ctype = request.content_type or ""
        if "multipart/form-data" in ctype:
            language = request.form.get("language", "unknown")
            if "test_output" in request.files:
                test_output = (
                    request.files["test_output"]
                    .read()
                    .decode("utf-8", errors="replace")
                )
            if "test_code" in request.files:
                test_code = (
                    request.files["test_code"].read().decode("utf-8", errors="replace")
                )
            if "source_code" in request.files:
                source_code = (
                    request.files["source_code"]
                    .read()
                    .decode("utf-8", errors="replace")
                )
        else:
            data = request.get_json(force=True, silent=True) or {}
            language = data.get("language", "unknown")
            test_output = data.get("test_output", "")
            test_code = data.get("test_code", "")
            source_code = data.get("source_code", "")
    except Exception as e:
        return jsonify({"error": f"Bad Request: {str(e)}"}), 400

    prompt = PROMPT_TEMPLATE.substitute(
        language=language,
        test_output=test_output,
        test_code=test_code,
        source_code=source_code,
    )

    model_analysis = call_model(prompt)

    html = HTML_TEMPLATE.substitute(
        language=language, test_output=test_output, model_analysis=model_analysis
    )

    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html)

    return send_file("report.html", mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
