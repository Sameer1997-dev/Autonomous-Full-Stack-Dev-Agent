import json
import re
import threading

import ollama

MODEL = "qwen2.5-coder:7b"

REVIEWER_PROMPT = """
You are the Reviewer component of an autonomous software development agent.

Your job is to independently verify whether the implementation satisfies
the original user request and development plan.

You are given:

1. The original user request.
2. The development plan.
3. The actual project file list.
4. The actual contents of relevant project files.
5. Actual test execution results.

You MUST evaluate the actual evidence.

Do NOT assume that a requirement is satisfied merely because:

- a file exists
- a developer claims it was implemented
- a test file exists
- a test command was executed

Inspect the actual source code provided.

Return ONLY valid JSON.

Use exactly this structure:

{
  "status": "PASS",
  "requirements": [
    {
      "requirement": "description",
      "status": "PASS",
      "evidence": "specific evidence from the actual files or test results"
    }
  ],
  "issues": [],
  "summary": "short review summary"
}

The status must be either:

"PASS"

or:

"FAIL"

REVIEW RULES:

1. Every explicit user requirement must be satisfied.

2. Every important requirement in the development plan must be addressed.

3. Verify implementation using actual source code whenever possible.

4. Verify tests using actual test execution results.

5. A failed test means the implementation cannot receive PASS.

    When test_results includes both "execution_history" and
    "latest_results", use "latest_results" to determine whether each
    command currently passes. Earlier failures followed by a successful
    rerun are recovered attempts and must not block PASS on their own.

6. A missing required file means FAIL.

7. A missing required feature means FAIL.

8. If the source code contradicts the requirement, mark it FAIL.

9. If evidence is insufficient to verify a requirement, mark it FAIL.

10. Do not invent evidence.

11. Do not claim to have inspected code that was not provided.

12. Evidence should reference concrete implementation details.

13. For example, if the requirement is:
    "Implement add(a, b)"

    acceptable evidence would be:
    "calculator.py contains def add(a, b): return a + b"

14. A statement such as "the file exists" is NOT sufficient evidence
    for an implementation requirement.

15. If there are issues, list them clearly in the issues array.

16. If all requirements are implemented and verified, return PASS.

17. Return ONLY valid JSON.
"""

def extract_json(content):
    """
    Extract JSON from the model response.

    Handles pure JSON and JSON accidentally wrapped
    inside Markdown code fences.
    """

    cleaned = content.strip()

    cleaned = re.sub(
        r"```(?:json)?",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    cleaned = cleaned.replace(
        "```",
        ""
    ).strip()

    decoder = json.JSONDecoder()

    try:
        data, _ = decoder.raw_decode(cleaned)
        return data

    except json.JSONDecodeError:

        match = re.search(
            r"\{.*\}",
            cleaned,
            flags=re.DOTALL
        )

        if not match:
            raise ValueError(
                "Reviewer did not return valid JSON."
            )

        try:
            return json.loads(
                match.group(0)
            )

        except json.JSONDecodeError as error:
            raise ValueError(
                f"Reviewer returned invalid JSON: {error}"
            )


def validate_review(review):
    """
    Validate the basic structure of the reviewer response.
    """

    required_fields = [
        "status",
        "requirements",
        "issues",
        "summary"
    ]

    for field in required_fields:

        if field not in review:
            raise ValueError(
                f"Reviewer output is missing: {field}"
            )

    if review["status"] not in [
        "PASS",
        "FAIL"
    ]:
        raise ValueError(
            "Reviewer status must be PASS or FAIL."
        )

    if not isinstance(
        review["requirements"],
        list
    ):
        raise ValueError(
            "Reviewer requirements must be a list."
        )

    if not isinstance(
        review["issues"],
        list
    ):
        raise ValueError(
            "Reviewer issues must be a list."
        )

    for requirement in review["requirements"]:

        if not isinstance(
            requirement,
            dict
        ):
            raise ValueError(
                "Each requirement review must be an object."
            )

        required_requirement_fields = [
            "requirement",
            "status",
            "evidence"
        ]

        for field in required_requirement_fields:

            if field not in requirement:
                raise ValueError(
                    f"Requirement review is missing: {field}"
                )

        if requirement["status"] not in [
            "PASS",
            "FAIL"
        ]:
            raise ValueError(
                "Requirement status must be PASS or FAIL."
            )

    return True


def review_project(
    user_request,
    development_plan,
    project_files,
    test_results
):
    """
    Review the completed implementation using actual
    project file contents and actual test results.
    """

    if isinstance(
        development_plan,
        dict
    ):
        development_plan_text = json.dumps(
            development_plan,
            indent=2
        )
    else:
        development_plan_text = str(
            development_plan
        )

    if isinstance(
        project_files,
        dict
    ):
        project_files_text = json.dumps(
            project_files,
            indent=2
        )

    elif isinstance(
        project_files,
        list
    ):
        project_files_text = "\n".join(
            project_files
        )

    else:
        project_files_text = str(
            project_files
        )

    if isinstance(
        test_results,
        dict
    ):
        test_results_text = json.dumps(
            test_results,
            indent=2
        )
    else:
        test_results_text = str(
            test_results
        )

    review_request = f"""
ORIGINAL USER REQUEST:

{user_request}

DEVELOPMENT PLAN:

{development_plan_text}

ACTUAL PROJECT FILES AND CONTENTS:

{project_files_text}

ACTUAL TEST RESULTS:

{test_results_text}

If the test results include "execution_history" and "latest_results",
use "latest_results" for the current outcome of each command. Treat an
earlier failed attempt as resolved only when that command was rerun and
its latest exit_code is 0.

Review the implementation now.

For every requirement:

1. Determine exactly what the requirement asks for.
2. Inspect the provided source code.
3. Compare the implementation against the requirement.
4. Check the actual test results.
5. Provide concrete evidence.
6. Mark the requirement PASS only when there is sufficient evidence.

Return ONLY the required JSON review.
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": REVIEWER_PROMPT
            },
            {
                "role": "user",
                "content": review_request
            }
        ]
    )

    content = response["message"]["content"]

    review = extract_json(content)

    validate_review(review)

    return review