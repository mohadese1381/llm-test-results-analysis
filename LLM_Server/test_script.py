import requests

url = "http://localhost:5000/analyze_project"
data = {
    "code": "def add(a, b): return a + b",
    "tests": """
import unittest
from main import add
class TestAdd(unittest.TestCase):
    def test_add_wrong(self):
        self.assertEqual(add(2, 2), 5)
""",
    "language": "python",
}
response = requests.post(url, json=data)

