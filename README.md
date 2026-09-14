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
- `README.md` — learning notes and setup instructions.

## Important ADK concepts

- `Agent` — an LLM-powered specialist with a focused instruction.
- `LoopAgent` — runs its child agents sequentially for a bounded number of iterations.
- `AgentTool` — exposes an agent or composite agent as a tool for another agent.
- `output_key` — writes an agent's response to session state.
- State interpolation — expressions such as `{blog_outline}` let instructions consume values created earlier in the workflow; optional values use `{key?}`.

## Limitations

This repository contains only the workflow definition. It does not include a
CLI wrapper, pinned dependency lockfile, automated evaluations, or a real
codebase-context loader. The checker instructions record feedback in state;
the bounded loop provides the retry budget, while production-grade stopping
criteria would be worth adding as the next experiment.
