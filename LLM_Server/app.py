from flask import Flask, request, send_file
import tempfile
import subprocess
from string import Template
import requests
import os

app = Flask(__name__)

API_URL = "https://api.together.xyz/v1/chat/completions"
API_KEY = "490acbd83989f44751fa2f6ec07bf7b9f247e5f87fa5309983be9e6622aa43eb"

headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

HTML_TEMPLATE = Template(
    """
<!DOCTYPE html>
<html lang="fa">
<head>
    <meta charset="UTF-8">
    <title>گزارش تحلیلی تست</title>
    <style>
        body { font-family: Tahoma, sans-serif; background: #f7f7f7; padding: 30px; color: #333; }
        h1, h2 { color: #2c3e50; text-align: center; }
        .block { background: #fff; padding: 20px; border-radius: 10px; margin-bottom: 30px; box-shadow: 0 0 10px rgba(0,0,0,0.05); }
        pre { background: #f0f0f0; padding: 15px; border-radius: 5px; direction: ltr; overflow-x: auto; }
        ul { direction: rtl; }
    </style>
</head>
<body>
    <h1>📄 گزارش تحلیلی تست</h1>
    <div class="block">
        <h2>📌 خلاصه تست</h2>
        <p><strong>زبان:</strong> $language</p>
        <p><strong>نتایج:</strong> مجموع: $total | موفق: $passed | ناموفق: $failed</p>
    </div>
    <div class="block">
        <h2>❌ موارد ناموفق</h2>
        <pre>$failures</pre>
    </div>
    <div class="block">
        <h2>🧠 تحلیل مدل</h2>
        <pre>$model_analysis</pre>
    </div>
</body>
</html>
"""
)

# پرامپت دقیق تخصصی
FIXED_PROMPT = Template(
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

Your output should be structured in this HTML format user like it and must be simple and not change every time. Just choose one clean format which includes:

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

Test Code:
$test_code

Test Output:
$test_output
"""
)


# فراخوانی مدل Together.ai
def call_llm(full_prompt):
    payload = {
        "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.5,
        "max_tokens": 1000,
    }
    res = requests.post(API_URL, headers=headers, json=payload)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]


@app.route("/analyze_project", methods=["POST"])
def analyze_project():
    data = request.json
    code = data.get("code", "")
    tests = data.get("tests", "")
    language = data.get("language", "python")

    temp_dir = tempfile.mkdtemp()
    code_path = os.path.join(temp_dir, "main.py")
    test_path = os.path.join(temp_dir, "test_main.py")

    with open(code_path, "w", encoding="utf-8") as f:
        f.write(code)
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(tests)

    try:
        result = subprocess.run(
            ["python", "-m", "unittest", "discover", temp_dir],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        output = "⏱️ تست بیش از حد طول کشید."

    total = output.count("test_")
    failed = output.count("FAIL")
    passed = total - failed
    failures = "\n".join(
        [line for line in output.splitlines() if "FAIL:" in line or "Traceback" in line]
    )

    full_prompt = FIXED_PROMPT.substitute(test_code=tests, test_output=output)

    model_analysis = call_llm(full_prompt)

    html_content = HTML_TEMPLATE.substitute(
        language=language,
        total=total,
        passed=passed,
        failed=failed,
        failures=failures,
        model_analysis=model_analysis,
    )

    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    return send_file("report.html", mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
