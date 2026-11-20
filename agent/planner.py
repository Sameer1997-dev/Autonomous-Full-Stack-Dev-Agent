import json
import re
import ollama

from agent.model import get_model



PLANNER_PROMPT = """
You are the planning component of an autonomous full-stack software
development agent.

Analyze the user's software development request and create a precise
implementation plan.

You MUST return ONLY valid JSON.

Do not use Markdown.
Do not use code fences.
Do not add explanations before or after the JSON.

Use exactly this structure:

{
  "requirements": [
    "requirement 1",
    "requirement 2"
  ],
  "files": [
    {
      "path": "example.py",
      "action": "create",
      "purpose": "description"
    }
  ],
  "technologies": [
    "Python"
  ],
  "steps": [
    "implementation step 1",
    "implementation step 2"
  ],
  "testing": [
    "test requirement 1",
    "test requirement 2"
  ],
  "risks": [
    "potential issue 1"
  ]
}

PLANNING RULES:

1. Extract EVERY explicit requirement from the user's request.

2. Do not remove or simplify user requirements.

3. Identify every file that needs to be created or modified.

4. Specify whether each file should be created or modified.

5. Identify the technologies required.

6. Break the implementation into logical steps.

7. Define how the implementation should be tested.

8. Identify realistic risks or potential issues.

9. Do not implement the project.

10. Do not invent requirements that are unrelated to the user's request.

11. Return ONLY valid JSON.
"""


def extract_json(content):
    """
    Extract JSON from the model response.

    Handles both pure JSON and JSON accidentally placed
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
                "Planner did not return valid JSON."
            )

        try:
            return json.loads(
                match.group(0)
            )

        except json.JSONDecodeError as error:
            raise ValueError(
                f"Planner returned invalid JSON: {error}"
            )


def validate_plan(plan):
    """
    Validate the basic structure of the planner output.
    """

    required_fields = [
        "requirements",
        "files",
        "technologies",
        "steps",
        "testing",
        "risks"
    ]

    for field in required_fields:

        if field not in plan:
            raise ValueError(
                f"Planner output is missing required field: {field}"
            )

    if not isinstance(plan["requirements"], list):
        raise ValueError(
            "Planner field 'requirements' must be a list."
        )

    if not isinstance(plan["files"], list):
        raise ValueError(
            "Planner field 'files' must be a list."
        )

    if not isinstance(plan["technologies"], list):
        raise ValueError(
            "Planner field 'technologies' must be a list."
        )

    if not isinstance(plan["steps"], list):
        raise ValueError(
            "Planner field 'steps' must be a list."
        )

    if not isinstance(plan["testing"], list):
        raise ValueError(
            "Planner field 'testing' must be a list."
        )

    if not isinstance(plan["risks"], list):
        raise ValueError(
            "Planner field 'risks' must be a list."
        )

    for file_info in plan["files"]:

        if not isinstance(file_info, dict):
            raise ValueError(
                "Each file entry must be an object."
            )

        if "path" not in file_info:
            raise ValueError(
                "Each file entry must contain 'path'."
            )

        if "action" not in file_info:
            raise ValueError(
                "Each file entry must contain 'action'."
            )

        if "purpose" not in file_info:
            raise ValueError(
                "Each file entry must contain 'purpose'."
            )

    return True


def create_plan(request):
    """
    Ask Qwen to create a structured development plan.
    """

    response = ollama.chat(
        model=get_model(),
        messages=[
            {
                "role": "system",
                "content": PLANNER_PROMPT
            },
            {
                "role": "user",
                "content": request
            }
        ]
    )

    content = response["message"]["content"]

    plan = extract_json(content)

    validate_plan(plan)

    return plan
