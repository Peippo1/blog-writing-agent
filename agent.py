"""A small Google ADK multi-agent workflow for drafting technical blog posts.

The root agent delegates to two bounded loops: planner -> outline checker and
writer -> blog-post checker. Each agent writes its result to session state with
``output_key`` so later agents can consume it.
"""

import os
from datetime import date

from dotenv import load_dotenv
from google.adk.agents import Agent, LoopAgent
from google.adk.tools.agent_tool import AgentTool

# Load values such as GOOGLE_API_KEY and MODEL from a local .env file when one
# is present. Secrets stay outside the source code.
load_dotenv()

# Keep model selection and retry behaviour in one place so experiments are easy
# to change without editing every agent definition.
MODEL = os.getenv("MODEL", "gemini-flash-latest")
MAX_ITERATIONS = 3


# First specialist: create the plan that the writer will follow. ADK saves the
# response under blog_outline, making it available to later agents in state.
blog_planner = Agent(
    name="BlogPlanner",
    model=MODEL,
    description="Creates a structured Markdown outline for a technical blog post.",
    instruction="""
You are a technical content strategist. Create a detailed Markdown outline for
the user's topic. Include a working title, introduction, 4-6 main sections,
useful sub-points, and a conclusion.

If `{codebase_context?}` exists in session state, use relevant names or snippets
from it. Otherwise, stay general and do not invent project details.

If `{outline_feedback?}` exists, revise the previous outline to address it.
Return only the outline in Markdown.
""",
    output_key="blog_outline",
)

# Second specialist: inspect the planner's output and save either "ok" or
# actionable revision notes under outline_feedback. The optional ? placeholders
# prevent the first pass from failing when feedback does not exist yet.
outline_checker = Agent(
    name="OutlineChecker",
    model=MODEL,
    description="Checks an outline for the minimum structure needed by the writer.",
    instruction="""
Review the outline in session state key `{blog_outline}`.

Check that it has a title, introduction, 4-6 main sections, and a conclusion,
and that the sections fit the user's topic. Store concise, actionable revision
feedback in `outline_feedback`. If it is valid, store `ok`.
""",
    output_key="outline_feedback",
)

# LoopAgent runs BlogPlanner and OutlineChecker in order. If the checker finds
# a problem, its feedback is available to the next planner pass. The iteration
# cap is a safety valve that prevents an endless retry loop.
robust_blog_planner = LoopAgent(
    name="RobustBlogPlanner",
    description="Regenerates an outline and reviews it for up to three passes.",
    sub_agents=[blog_planner, outline_checker],
    max_iterations=MAX_ITERATIONS,
)


# Third specialist: turn the approved outline into a complete Markdown article.
# It can also use blog_feedback when the writer loop is on a later pass.
blog_writer = Agent(
    name="BlogWriter",
    model=MODEL,
    description="Writes a complete technical Markdown article from the outline.",
    instruction="""
Write a complete, accurate, and engaging technical blog post from
`{blog_outline}` in session state. Explain both how and why the system works.
Use headings, lists, and short code snippets where they improve understanding.

If `{codebase_context?}` exists, weave in only details supported by it. If
`{blog_feedback?}` exists, revise the previous draft to address it.

Return only the article in Markdown.
""",
    output_key="blog_post",
)

# Final specialist: compare the draft with the outline and store revision notes
# for the next BlogWriter pass.
blog_post_checker = Agent(
    name="BlogPostChecker",
    model=MODEL,
    description="Checks the generated article for structure, clarity, and outline coverage.",
    instruction="""
Review `{blog_post}` against `{blog_outline}` in session state.

Check for a title, introduction, 4-6 substantive sections, a conclusion,
clarity, and alignment with the outline. Store concise, actionable revision
feedback in `blog_feedback`. If it is valid, store `ok`.
""",
    output_key="blog_feedback",
)

# The writing loop uses the same plan -> review pattern as the planner loop,
# but its shared state is blog_post/blog_feedback instead.
robust_blog_writer = LoopAgent(
    name="RobustBlogWriter",
    description="Regenerates and reviews a blog post for up to three passes.",
    sub_agents=[blog_writer, blog_post_checker],
    max_iterations=MAX_ITERATIONS,
)


# AgentTool exposes each composite loop as a callable tool to the root agent.
# This is the delegation boundary: Blogger decides when to invoke each loop.
planner_tool = AgentTool(agent=robust_blog_planner)
writer_tool = AgentTool(agent=robust_blog_writer)


# Root coordinator: plan first, then write. The final instruction also asks for
# publishing extras (alternative titles and LinkedIn hooks) after the article.
root_agent = Agent(
    name="Blogger",
    model=MODEL,
    description="Coordinates outline planning, validation, and technical blog writing.",
    instruction=f"""
You are the root coordinator for a technical blog-writing workflow.

1. Call the `RobustBlogPlanner` tool to create and validate an outline.
2. Call the `RobustBlogWriter` tool to draft and validate the article from that outline.
3. Return the final Markdown article.
4. End with three alternative titles, each with a one-sentence rationale, and
   two LinkedIn hooks per title: one short and one long.

Continue with a sensible outline and draft if a delegated tool fails or times
out. Today's date is {date.today().isoformat()}.
""",
    tools=[planner_tool, writer_tool],
)
