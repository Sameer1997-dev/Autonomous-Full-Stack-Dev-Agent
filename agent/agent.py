import json
import re
import ollama

from agent.reviewer import review_project
from tools.files import list_files, read_file, write_file
from tools.terminal import run_command


MODEL = "qwen2.5-coder:7b"
MAX_STEPS = 15


SYSTEM_PROMPT = """
You are an autonomous full-stack software development agent.

Your job is to turn the user's requirements into a working software project.

You have access to these tools:

1. list_files
   - Lists files inside the agent workspace.

2. read_file
   - Reads an existing file from the workspace.

3. write_file
   - Creates or completely replaces a file in the workspace.

4. run_command
   - Runs a development command inside the workspace.


TOOL FORMAT:

{
  "action": "tool",
  "tool": "tool_name",
  "arguments": {}
}


For write_file:

{
  "action": "tool",
  "tool": "write_file",
  "arguments": {
    "filename": "example.py",
    "content": "..."
  }
}


For read_file:

{
  "action": "tool",
  "tool": "read_file",
  "arguments": {
    "filename": "example.py"
  }
}


For run_command:

{
  "action": "tool",
  "tool": "run_command",
  "arguments": {
    "command": "python example.py"
  }
}


IMPORTANT DEVELOPMENT RULES:

1. Understand ALL requirements before implementing anything.

2. If a development plan is provided, follow the plan.

3. Implement EVERY explicit user requirement.

4. Do not replace a required feature with a simpler alternative.

5. Before modifying an existing project, inspect the relevant files.

6. Do not create duplicate or conflicting implementations.

7. When modifying an existing file, read it first when necessary so that
   existing functionality is not accidentally overwritten.

8. After implementation, inspect the project files when appropriate.

9. Run automated tests whenever tests are required.

10. A command returning exit_code 0 does NOT automatically mean the
    application works correctly. The command must actually verify the
    intended behavior.


FAILURE HANDLING:

11. A command returning exit_code != 0 means the task is NOT complete.

12. When a command or test fails, carefully read the COMPLETE error output.

13. Identify the exact cause of the failure.

14. Inspect the exact relevant file mentioned in the error using read_file.

15. After inspecting the file, make the required correction using
    write_file.

16. Do NOT merely describe the fix. You MUST actually execute write_file.

17. Never claim that a file was modified unless write_file returns:
    "File written successfully".

18. After making a fix, run the failing test or command again.

19. Do not repeat the same failed command unless a relevant change was
    made first.

20. If the same command fails with substantially the same error twice,
    stop repeating it. Inspect the relevant files and determine what
    change is actually required.

21. If a failure is caused by a missing dependency, first determine whether
    that dependency is actually required by the current project.

22. Do not install packages blindly. Prefer the project's existing
    dependencies and test framework.

23. If an existing test belongs to an older or unrelated project feature,
    inspect it before changing it. Do not break unrelated functionality
    just to make the current task pass.

24. If the current task only requires testing specific files, test those
    files rather than blindly running every old test in the workspace.


TESTING RULES:

25. When the user requests a specific feature, prefer tests directly
    related to that feature.

26. For example, if the task is:

    Create calculator.py with an add(a, b) function and create an
    automated unittest for it.

    Prefer:

    python -m unittest test_calculator.py

    rather than:

    pytest

27. If the user explicitly asks for the entire project test suite,
    run the complete suite.

28. If a test passes, treat it as verified only for the behavior covered
    by that test.

29. Before declaring success, verify that all explicit user requirements
    have actually been implemented.

30. Before declaring success, run the relevant final test command.

31. The final test command MUST return exit_code 0 before claiming that
    the task is complete.

32. Never invent test results.

33. Never report expected output as actual output.

34. Only report test results that were actually returned by run_command.


TOOL USAGE RULES:

35. Use list_files when you need to understand the workspace structure.

36. Use read_file before changing an existing file when its current
    contents are relevant.

37. Use write_file to actually create or modify files.

38. Use run_command to execute tests and development commands.

39. When a tool returns a failure, use the failure information to decide
    the next action.

40. Do not stop merely because files were created.

41. Do not stop merely because one test passed.

42. Continue working until the user's requirements are implemented and
    appropriately verified, or a genuine external limitation prevents
    completion.

43. If a genuine external limitation prevents completion, clearly state
    the limitation instead of claiming success.


FINAL RESPONSE RULES:

44. Do not claim the project is complete unless the requirements have
    been verified.

45. Before finishing, verify each requirement individually.

46. Provide a final summary containing:

    - What was implemented
    - Files created/modified
    - Tests executed
    - Actual test results
    - Any remaining issues

47. If tests failed, clearly state that they failed.

48. Never claim success when the final relevant test has a non-zero
    exit code.

49. Never claim a file was created or modified unless the corresponding
    tool result confirms it.

50. Do not confuse a development plan or expected result with actual
    execution results.

When you need to use a tool, output one or more JSON tool calls.

Do not invent tool names.

After tools are executed, continue working on the original task.
"""


def execute_tool(tool_name, arguments):
    """
    Execute one of the available development tools.
    """

    if tool_name == "list_files":
        return list_files()

    if tool_name == "read_file":
        filename = (
            arguments.get("filename")
            or arguments.get("file_path")
        )

        if not filename:
            return "ERROR: filename is required."

        return read_file(filename)

    if tool_name == "write_file":
        filename = (
            arguments.get("filename")
            or arguments.get("file_path")
        )

        content = arguments.get("content", "")

        if not filename:
            return "ERROR: filename is required."

        return write_file(
            filename,
            content
        )

    if tool_name == "run_command":
        command = arguments.get("command")

        if not command:
            return "ERROR: command is required."

        return run_command(command)

    return f"ERROR: Unknown tool: {tool_name}"


def extract_tool_calls(content):
    """
    Extract JSON tool calls from the model response.

    Handles JSON inside markdown code fences and normal text.
    """

    cleaned = re.sub(
        r"```(?:json)?",
        "",
        content,
        flags=re.IGNORECASE
    )

    cleaned = cleaned.replace(
        "```",
        ""
    )

    decoder = json.JSONDecoder()

    tool_calls = []

    position = 0

    while position < len(cleaned):

        match = re.search(
            r'\{\s*"action"\s*:\s*"tool"',
            cleaned[position:]
        )

        if not match:
            break

        start = position + match.start()

        try:
            data, end = decoder.raw_decode(
                cleaned[start:]
            )

            if data.get("action") == "tool":
                tool_calls.append(data)

            position = start + end

        except json.JSONDecodeError:
            position = start + 1

    return tool_calls


def format_tool_result(tool_name, result):
    """
    Convert tool results into a clear structured message for the model.
    """

    if isinstance(result, dict) and "exit_code" in result:

        exit_code = result["exit_code"]

        if exit_code == 0:
            status = "SUCCESS"
        else:
            status = "FAILURE"

        return f"""
Tool: {tool_name}

Status: {status}

Exit Code: {exit_code}

Output:
{result.get("output", "")}
"""

    return f"""
Tool: {tool_name}

Status: SUCCESS

Result:
{result}
"""


def review_current_implementation(user_request, development_plan, test_result=None):
    """
    Run the reviewer against the current workspace and test evidence.
    """

    if test_result is None:
        test_result = {
            "command": "No command executed",
            "exit_code": 0,
            "output": "No test output was captured."
        }

    project_files = list_files()

    review = review_project(
        user_request=user_request,
        development_plan=development_plan,
        project_files=project_files,
        test_results=test_result
    )

    print("\n=== REVIEWER RESULT ===")
    print(json.dumps(review, indent=2))

    return review


def run_agent(user_request, development_plan=None):
    """
    Run the autonomous developer agent.

    Returns a summary containing:
    - whether the agent stopped normally
    - tools executed
    - command/test results
    - files currently in the workspace
    """

    if development_plan is not None:
        development_plan_text = json.dumps(
            development_plan,
            indent=2
        )
    else:
        development_plan_text = None

    if development_plan:
        initial_request = f"""
ORIGINAL USER REQUEST:
{user_request}

DEVELOPMENT PLAN:
{development_plan_text}

INSTRUCTIONS:
You MUST use the development plan as guidance while implementing
the original user request.

The plan is guidance, not a substitute for the original requirements.

If the plan conflicts with the user's explicit requirements,
follow the user's explicit requirements.

Do not merely describe the plan.

Actually implement the requirements using the available tools.

Inspect existing files when necessary.

Create or modify the required files.

Run the relevant tests.

If a test fails, diagnose the failure, inspect the relevant files,
make the actual correction using write_file, and run the test again.

Do not claim success until the relevant final test passes.
"""
    else:
        initial_request = user_request

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": initial_request
        }
    ]

    previous_failures = {}
    tools_executed = []
    command_results = []
    stopped_normally = False
    step_count = 0

    for step in range(MAX_STEPS):
        step_count = step + 1
        print(f"\n--- Agent Step {step_count} ---\n")

        response = ollama.chat(
            model=MODEL,
            messages=messages
        )

        content = response["message"]["content"]
        print(content)

        messages.append(
            {
                "role": "assistant",
                "content": content
            }
        )

        tool_calls = extract_tool_calls(content)

        if not tool_calls:
            stopped_normally = True
            return {
                "status": "COMPLETED",
                "step_count": step_count,
                "stopped_normally": True,
                "tools_executed": tools_executed,
                "command_results": command_results,
                "workspace_files": list_files(),
            }

        results = []
        last_run_command_result = None

        for call in tool_calls:
            tool_name = call.get("tool")
            arguments = call.get("arguments", {})

            print(f"\nExecuting tool: {tool_name}")

            result = execute_tool(tool_name, arguments)

            tools_executed.append({
                "tool": tool_name,
                "arguments": arguments,
                "result": result
            })

            if tool_name == "run_command":
                last_run_command_result = result
                command_results.append({
                    "command": arguments.get("command"),
                    "result": result
                })

            print(f"Tool result:\n{result}")

            formatted_result = format_tool_result(tool_name, result)
            results.append(formatted_result)

            if (
                isinstance(result, dict)
                and "exit_code" in result
                and result.get("exit_code") != 0
            ):
                command = arguments.get("command", "")
                failure_key = (
                    tool_name,
                    command,
                    result.get("output", "")
                )
                previous_failures[failure_key] = previous_failures.get(failure_key, 0) + 1
                failure_count = previous_failures[failure_key]

                print("\nTOOL FAILURE DETECTED")
                print(f"Failure repetition count: {failure_count}")

                if failure_count >= 2:
                    results.append(
                        """
IMPORTANT:

This same failure has occurred multiple times.

DO NOT repeat the same command again.

You MUST inspect the relevant files and make
a meaningful correction before retrying.
"""
                    )

        messages.append(
            {
                "role": "user",
                "content": f"""
The requested tools have been executed.

Tool results:

{''.join(results)}


Continue working on the ORIGINAL user request.

IMPORTANT:

- Treat exit_code != 0 as a failure.
- Do not claim the task is complete after a failed command.
- Inspect the relevant files when a command fails.
- Make the actual fix using write_file.
- Confirm write_file succeeds.
- Then run the relevant test again.
- Do not repeat the same failed command without making a relevant change.
- Only declare success after the final relevant test returns exit_code 0.
- Do not report expected output as actual output.
- Verify all explicit requirements before finishing.
"""
            }
        )

    return {
        "status": "MAX_STEPS_REACHED",
        "step_count": step_count,
        "stopped_normally": stopped_normally,
        "tools_executed": tools_executed,
        "command_results": command_results,
        "workspace_files": list_files(),
    }