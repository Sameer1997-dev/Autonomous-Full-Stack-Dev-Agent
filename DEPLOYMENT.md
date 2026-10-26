# Deployment plan: Render

The chosen hosting target is Render. The current app is still **local-only**. Do not create a public service from this code yet: it can run model-generated shell commands, and a bearer token alone is not a safe execution boundary for a public agent.

## Local run

1. Install Python 3.10 or newer and Ollama.
2. Install dependencies from `requirements.txt` in a virtual environment.
3. Pull the configured model once: `ollama pull qwen2.5-coder:7b`.
4. Set `AGENT_WEB_TOKEN` in your shell to a random secret of at least 24 characters. The project already has a local `.env`; do not overwrite it. `.env.example` is only a reference and is not loaded automatically.
5. Run `python web_app.py` from this project folder and open `http://127.0.0.1:8765`.

The service deliberately binds to loopback only. Requests and job results currently live in memory; work is serialized through one worker because all requests share the same workspace.

## Before publishing on Render

- Run the project checks and confirm the service starts.
- Add a disposable, isolated execution worker per job. It must not share the web process's secrets, and it needs strict CPU, memory, time, filesystem, and network limits.
- Move job state and artifacts to managed persistent storage, with per-user authentication and quotas.
- Configure a reachable model endpoint and store its credentials only as Render runtime secrets.
- Add a production server, health check, TLS, and structured logging. Bind to the Render-provided port only after the execution worker is isolated.
- Create a private Git repository or a reviewed container image for the Render service. Keep `.env`, virtual environments, and user secrets out of the source and image.

Render deploys a web service from a connected Git repository or a container image. The project currently has no Git repository, no Render connection, and no hosted model endpoint configured. No public Render service has been created.

