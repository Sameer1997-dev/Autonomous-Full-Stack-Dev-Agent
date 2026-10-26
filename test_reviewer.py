import json

from agent.reviewer import review_project

user_request = """
Create calculator.py with an add(a, b) function and create
an automated unittest for it. Run the test and fix any errors
until it passes.
"""

development_plan = {
    "requirements": [
        "Create calculator.py",
        "Implement an add(a, b) function",
        "Create an automated unittest",
        "Run the test and fix errors until it passes"
    ],
    "files": [
        {
            "path": "calculator.py",
            "action": "create",
            "purpose": "Contains the add function"
        },
        {
            "path": "test_calculator.py",
            "action": "create",
            "purpose": "Contains automated tests"
        }
    ],
    "technologies": [
        "Python",
        "unittest"
    ],
    "steps": [
        "Create calculator.py",
        "Create test_calculator.py",
        "Run the unittest",
        "Fix failures if necessary"
    ],
    "testing": [
        "Run python -m unittest test_calculator.py"
    ],
    "risks": []
}

project_files = {
    "calculator.py": """def add(a, b):\n    return a + b\n""",
    "test_calculator.py": """import unittest\n\nfrom calculator import add\n\n\nclass TestCalculator(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n        self.assertEqual(add(-1, 1), 0)\n        self.assertEqual(add(0, 0), 0)\n        self.assertEqual(add(-5, -5), -10)\n\n\nif __name__ == '__main__':\n    unittest.main()\n"""
}

test_results = {
    "command": "python -m unittest test_calculator.py",
    "exit_code": 0,
    "output": ".\n----------------------------------------------------------------------\nRan 1 test in 0.000s\n\nOK"
}

review = review_project(
    user_request=user_request,
    development_plan=development_plan,
    project_files=project_files,
    test_results=test_results
)

print("\n================================")
print("REVIEW RESULT")
print("================================\n")

print(
    json.dumps(
        review,
        indent=2
    )
)