# Deployment plan: Render

The chosen hosting target is Render. The local browser app is **not ready for public deployment**. Do not create a public service from this code yet: it can run model-generated shell commands, and a bearer token alone is not a safe execution boundary for a public agent.

## Local run

1. Install Python 3.10 or newer and Ollama.
2. Install dependencies from `requirements.txt` in a virtual environment.
3. Pull the configured model once: `ollama pull qwen2.5-coder:7b`.
4. Set `AGENT_WEB_TOKEN` in your shell to a random secret of at least 24 characters. The project already has a local `.env`; do not overwrite it. `.env.example` is only a reference and is not loaded automatically.
5. Run `python web_app.py` from this project folder and open `http://127.0.0.1:8765`.

The service binds to loopback by default. Requests and job results currently live in memory; work is serialized through one worker because all requests share the same workspace.

## Before publishing on Render

- Run the project checks and confirm the service starts.
- Use the Render Sandbox adapter for untrusted commands. It creates a short-lived isolated sandbox with resource and network limits per request.
- Move job state and artifacts to managed persistent storage, with per-user authentication and quotas.
- Configure a reachable model endpoint and store its credentials only as Render runtime secrets.
- Use a production server, configure the Render health check to /healthz, enable TLS, and add structured logging. Set AGENT_WEB_HOST=0.0.0.0 and let Render provide PORT only after the execution worker is isolated.
- Create a private Git repository or a reviewed container image for the Render service. Keep `.env`, virtual environments, and user secrets out of the source and image.

Render deploys a web service from a connected Git repository or a container image. The project is pushed to GitHub. No hosted model endpoint is configured, and no public Render service has been created.

The command runner now supports Render Sandboxes through the Render Python SDK (`render>=1.9.0`). When `RENDER=true`, the app defaults to isolated sandbox execution and refuses to run commands locally. Each request creates a sandbox only when the agent first needs to execute a command; commands are capped at 30 seconds, sandboxes at 15 minutes, and sandbox egress is restricted to package registries and GitHub. Workspace sync excludes common credential files and dependency folders, rejects links/special files, and caps transfers at 100 MB. Configure `RENDER_API_KEY` as a Render secret and `RENDER_SANDBOX_GROUP_ID` after sandbox access is available. Render Sandboxes may incur usage charges; check current pricing before enabling them.

A no-card preview can use a Free Render Web Service, but without sandbox access it must remain non-executing. The hosted service also needs a reachable model endpoint; Ollama's default localhost address is not reachable from Render.
