import json

from agent.planner import create_plan
from agent.agent import run_agent
from agent.reviewer import review_project
from tools.files import read_file

MAX_REVIEW_ATTEMPTS = 3


def collect_project_files(development_plan):
    """Collect contents only for files named in the development plan."""
    files = {}

    planned_files = development_plan.get("files", [])

    for file_info in planned_files:
        filename = file_info.get("path")
        if not filename:
            continue

        try:
            files[filename] = read_file(filename)
        except Exception as error:
            files[filename] = f"ERROR READING FILE: {error}"

    return files


def collect_test_results(agent_result):
    """Extract actual test/command results from the Developer Agent."""
    commands = [
        {
            "command": item.get("command"),
            **(item.get("result") or {})
        }
        for item in (agent_result or {}).get("command_results", [])
    ]
    latest_by_command = {}

    for result in commands:
        latest_by_command[result.get("command")] = result

    return {
        "agent_status": (agent_result or {}).get("status", "UNKNOWN"),
        "execution_history": commands,
        "latest_results": list(latest_by_command.values()),
    }


def main():
    request = input("\nWhat would you like me to build?\n> ")

    print("\n================================")
    print("DEVELOPMENT PLAN")
    print("================================\n")

    try:
        plan = create_plan(request)
    except Exception as error:
        print(f"\nPlanner error: {error}")
        raise SystemExit(1)

    print(json.dumps(plan, indent=2))

    review = None

    for attempt in range(1, MAX_REVIEW_ATTEMPTS + 1):
        print("\n================================")
        print(f"STARTING DEVELOPMENT AGENT (ATTEMPT {attempt})")
        print("================================")

        if review is None:
            developer_request = request
        else:
            developer_request = f"""
ORIGINAL USER REQUEST:
{request}

REVIEWER FEEDBACK FROM THE PREVIOUS ATTEMPT:
{json.dumps(review, indent=2)}

Fix every reported issue. Inspect the relevant files, make the corrections,
and run the relevant tests again. Do not claim completion until the issues
are resolved.
"""

        agent_result = run_agent(
            user_request=developer_request,
            development_plan=plan
        )

        print("\n================================")
        print("DEVELOPER RESULT")
        print("================================")
        print(json.dumps(agent_result, indent=2))

        project_files = collect_project_files(plan)
        test_results = collect_test_results(agent_result)

        print("\n================================")
        print(f"REVIEWER CHECK (ATTEMPT {attempt})")
        print("================================")

        try:
            review = review_project(
                user_request=request,
                development_plan=plan,
                project_files=project_files,
                test_results=test_results
            )
        except Exception as error:
            review = {
                "status": "FAIL",
                "requirements": [],
                "issues": [f"Reviewer could not produce a valid review: {error}"],
                "summary": "Review failed because the reviewer response was invalid."
            }

        print(json.dumps(review, indent=2))

        if review.get("status") == "PASS":
            print("\nReviewer decision: PASS")
            break

        print("\nReviewer decision: FAIL")
        if attempt < MAX_REVIEW_ATTEMPTS:
            print("Sending the review findings back to the Developer Agent.")
    else:
        print(
            f"\nStopped after {MAX_REVIEW_ATTEMPTS} review attempts; "
            "the implementation still has unresolved review findings."
        )


if __name__ == "__main__":
    main()
