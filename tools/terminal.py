import subprocess
from pathlib import Path


WORKSPACE = Path("workspace").resolve()


def run_command(command):
    """
    Execute a development command inside the workspace.
    """

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=30
        )

        output = result.stdout

        if result.stderr:
            output += "\n" + result.stderr

        return {
            "exit_code": result.returncode,
            "output": output.strip()
        }

    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "output": "Command timed out after 30 seconds."
        }

    except Exception as e:
        return {
            "exit_code": -1,
            "output": str(e)
        }