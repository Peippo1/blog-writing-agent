# Google ADK Blog-Writing Agent

An intentionally small learning project that demonstrates a bounded agent loop
with Google's Agent Development Kit (ADK). The workflow turns a topic into a
technical blog post by separating planning, checking, writing, and checking.

It is inspired by the Google Tech Team walkthrough in [this YouTube video](https://www.youtube.com/watch?v=Zqno_vux6d8), but the implementation here has been adapted and tidied up for this project.

Editable architecture: [open the FigJam diagram](https://www.figma.com/board/aYaxrqHlXNhZU3ScNjk10Y/?utm_source=chatgpt&utm_content=edit_in_figjam).

## What it does

```text
User topic
    |
    v
Blogger (root agent)
    |
    +--> RobustBlogPlanner (LoopAgent, max 3 passes)
    |       +--> BlogPlanner       -> blog_outline
    |       +--> OutlineChecker    -> outline_feedback
    |
    +--> RobustBlogWriter (LoopAgent, max 3 passes)
            +--> BlogWriter        -> blog_post
            +--> BlogPostChecker   -> blog_feedback
```

The root `Blogger` delegates to two `AgentTool` instances. Each tool wraps a
`LoopAgent` whose sub-agents run in sequence. ADK session state connects the
steps: `output_key` stores the outline, draft, and checker feedback so later
agents can read them.

## Why the loops exist

The planner loop gives the outline a basic structure before writing. The writer
loop checks the draft against that outline. Feedback is stored for the next
pass, and `max_iterations=3` prevents an endless retry cycle. This is a simple
teaching pattern; a production workflow would usually add stronger structured
outputs, deterministic validators, tracing, and tests/evaluations.

## Run locally

Use Python 3.11+ and install the dependencies:

```bash
python -m pip install google-adk python-dotenv
```

Set a model credential in your environment. For a Gemini API key, create a
`.env` file:

```dotenv
GOOGLE_API_KEY=your-key-here
MODEL=gemini-flash-latest
```

Then run the agent with the ADK CLI from the project directory:

```bash
adk web .
```

Open the local ADK web UI, select the project, and provide a topic such as:
`Explain how an agent loop improves a blog-writing workflow.`

## File guide

- `agent.py` — agent definitions, loop orchestration, state keys, and root agent.
- `creative-agent/agents.py` — a separate StoryForge experiment that creates
  original high-fantasy MMO regions and multi-stage questlines.
- `README.md` — learning notes and setup instructions.

### Try the creative agent

From the `creative-agent` directory, run the ADK web UI:

```bash
cd creative-agent
../.venv/bin/adk web .
```

Try a prompt such as `A storm-battered floating kingdom is losing its memories
to a creature beneath the clouds.`

## Important ADK concepts

- `Agent` — an LLM-powered specialist with a focused instruction.
- `LoopAgent` — runs its child agents sequentially for a bounded number of iterations.
- `AgentTool` — exposes an agent or composite agent as a tool for another agent.
- `output_key` — writes an agent's response to session state.
- State interpolation — expressions such as `{blog_outline}` let instructions consume values created earlier in the workflow; optional values use `{key?}`.

## Limitations

The original agent remains a compact learning workflow. The publishing studio
below adds the application boundary, persistence, authentication, and release
controls needed for a hosted workflow; it deliberately does not add autonomous
research, fact-checking, image generation, or direct LinkedIn posting.

## Publishing Studio

The repository now includes a private publishing-studio foundation in `app/`
and `web/`. It turns an article brief into an editable outline and Markdown
draft, lets the author request reviewable text expansions, queues one approved
article for a Friday release, opens a portfolio pull request, and produces a
manual LinkedIn package only after the article is live.

### Local development

1. Create a virtual environment and install the backend dependencies:

   ```bash
   python -m pip install -r requirements-dev.txt
   ```

2. Copy `.env.example` to `.env`. For local UI development only, set
   `DEV_BYPASS_AUTH=true` and use a placeholder `PORTFOLIO_REPOSITORY`.
   Never enable the bypass in a deployed environment.

3. Start the API:

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

4. Start the React UI in a second terminal:

   ```bash
   cd web
   npm install
   npm run dev
   ```

### Production configuration

- Deploy the Docker image to Cloud Run with a dedicated service account.
- Configure Firebase Authentication and `ALLOWED_EMAILS`; production requests
  require a verified Firebase bearer token and an allowlisted email.
- Store `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`,
  `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`, and `SCHEDULER_SECRET` in
  Secret Manager. The publisher mints a short-lived GitHub App installation
  token per publishing action. `GITHUB_TOKEN` is a development-only fallback
  and is rejected in production.
- Set the `PORTFOLIO_*` values to match the private portfolio repository's
  content path and front-matter schema. The scheduler creates a PR only; it
  never merges or publishes directly.
- Register the `/webhooks/github` endpoint for pull-request events and use
  `cloud-scheduler.yaml` as the Friday 09:00 Europe/London schedule template.

### Verification

```bash
python -m pytest
cd web && npm run build
```
