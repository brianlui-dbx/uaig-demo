"""MLflow AgentServer entry point (customized from the agent-langgraph template).

The upstream template sets ``enable_chat_proxy=True``, which proxies ``/`` to a **separate**
Next.js chat frontend (``e2e-chatbot-app-next``) running on ``CHAT_APP_PORT`` (3000). That
frontend needs Node at runtime + a git clone at startup, which is fragile inside Databricks
Apps — with no frontend process the proxy just returns 503 at ``/``.

Instead we serve a self-contained static chat page (``static/index.html``) straight from this
FastAPI app, so opening the App URL gives a working UI with no second process, no Node, and no
clone. The page POSTs to the same ``/invocations`` endpoint the API exposes.
"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from mlflow.genai.agent_server import AgentServer, setup_mlflow_git_based_version_tracking

# Load env vars from .env before importing the agent for proper auth.
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

import logging as _logging

import agent_server.agent  # noqa: E402  (import registers the @invoke/@stream handlers)

# chat_proxy OFF — we serve our own static UI below instead of proxying to a Node frontend.
agent_server = AgentServer("ResponsesAgent", enable_chat_proxy=False)

# Module-level app enables multiple workers.
app = agent_server.app
try:
    setup_mlflow_git_based_version_tracking()
except Exception as _e:
    _logging.getLogger(__name__).warning("MLflow version tracking skipped: %s", _e)

# Serve the built-in chat UI at / (mounted last so the AgentServer's API routes —
# /invocations, /responses, /agent/info, /health — keep priority). html=True makes "/" return
# index.html.
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="chat-ui")


def main():
    agent_server.run(app_import_string="agent_server.start_server:app")


if __name__ == "__main__":
    main()
