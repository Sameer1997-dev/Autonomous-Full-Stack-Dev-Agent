import os
import subprocess
from pathlib import Path

from tools.render_sandbox import _session, execution_mode


WORKSPACE = Path("workspace").resolve()


def run_command(command):
    """
    Execute a development command inside the workspace.
    """

    mode = execution_mode()
    if mode == "render":
        session = _session.get()
        if session is None:
            return {"exit_code": -1, "output": "No isolated sandbox is active for this job."}
        try:
            return session.run(command)
        except Exception as error:
            return {"exit_code": -1, "output": f"Isolated command failed: {type(error).__name__}: {error}"}

    if mode != "local" or os.environ.get("RENDER") == "true":
        return {"exit_code": -1, "output": "Local shell execution is disabled in this deployment."}

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
