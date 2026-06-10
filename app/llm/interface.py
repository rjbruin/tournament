"""
LLM query interface using OpenRouter (OpenAI-compatible chat completions API)
with tool use.

The model receives the user question and a set of tools that surface the
simulation statistics. It picks which stats to fetch, calls the tools,
and synthesises a natural-language answer.

The OpenRouter API key and model are configurable on the Settings page
(stored in data/settings.json) and fall back to the OPENROUTER_API_KEY /
OPENROUTER_MODEL environment variables.
"""

import json
import os
from typing import Any

import requests

from app.web.view_helpers import normalize_group_match, normalize_bracket_match, utc_sort_key

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _get_config(user_settings: dict | None) -> tuple[str, str]:
    settings = user_settings or {}
    api_key = settings.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", "")
    model = settings.get("openrouter_model") or os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")
    return api_key, model


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI / OpenRouter "function" tool format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_winner_probabilities",
            "description": "Returns each team's probability of winning the tournament, sorted by probability descending.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_finalist_probabilities",
            "description": "Returns each team's probability of reaching the final (top 2).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_semifinal_probabilities",
            "description": "Returns each team's probability of reaching the semi-finals (top 4).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quarterfinal_probabilities",
            "description": "Returns each team's probability of reaching the quarter-finals (top 8).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_advance_probabilities",
            "description": "Returns each team's probability of advancing from the group stage.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_stats",
            "description": "Returns full probability breakdown for a specific team across all rounds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "Exact team name (e.g. 'France', 'Brazil')."
                    }
                },
                "required": ["team_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fixtures",
            "description": (
                "Returns fixture details (teams, kickoff date/time/venue, and either the "
                "actual result if played or the simulated win/draw/loss probabilities). "
                "Optionally filter by group, by team, or to only the knockout bracket."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "group_name": {
                        "type": "string",
                        "description": "Optional group letter (e.g. 'A') to restrict to that group's fixtures."
                    },
                    "team_name": {
                        "type": "string",
                        "description": "Optional exact team name to restrict to fixtures involving that team (group stage and/or knockout)."
                    },
                    "round": {
                        "type": "string",
                        "description": "Optional: 'group' for group-stage fixtures only, or 'knockout' for bracket fixtures only. Omit for both."
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_stats",
            "description": "Returns all teams in a group with their advance and win probabilities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_name": {
                        "type": "string",
                        "description": "Group letter, e.g. 'A', 'B', …, 'L'."
                    }
                },
                "required": ["group_name"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _execute_tool(name: str, inputs: dict, engine, results: dict) -> str:
    if results is None:
        return json.dumps({"error": "No simulation results available."})

    def sorted_prob(prob_dict):
        return sorted(prob_dict.items(), key=lambda x: x[1], reverse=True)

    if name == "get_winner_probabilities":
        return json.dumps([{"team": t, "probability": p} for t, p in sorted_prob(results["winner_prob"])])

    if name == "get_finalist_probabilities":
        return json.dumps([{"team": t, "probability": p} for t, p in sorted_prob(results["finalist_prob"])])

    if name == "get_semifinal_probabilities":
        return json.dumps([{"team": t, "probability": p} for t, p in sorted_prob(results["semifinal_prob"])])

    if name == "get_quarterfinal_probabilities":
        return json.dumps([{"team": t, "probability": p} for t, p in sorted_prob(results["quarterfinal_prob"])])

    if name == "get_group_advance_probabilities":
        out = {}
        for g in engine.groups:
            out[g["name"]] = {t: results["group_advance_prob"].get(t, 0) for t in g["teams"]}
        return json.dumps(out)

    if name == "get_team_stats":
        team_name = inputs.get("team_name", "")
        if team_name not in engine.team_idx:
            # Try case-insensitive match
            match = next((n for n in engine.team_names if n.lower() == team_name.lower()), None)
            if match:
                team_name = match
            else:
                return json.dumps({"error": f"Team '{team_name}' not found."})
        tidx = engine.team_idx[team_name]
        team_data = engine.data["teams"][tidx]
        group = next(g for g in engine.groups if team_name in g["teams"])
        return json.dumps({
            "name": team_name,
            "elo": team_data["elo"],
            "confederation": team_data["confederation"],
            "group": group["name"],
            "group_advance_prob": results["group_advance_prob"].get(team_name, 0),
            "round_of_16_prob": results["round_of_16_prob"].get(team_name, 0),
            "quarterfinal_prob": results["quarterfinal_prob"].get(team_name, 0),
            "semifinal_prob": results["semifinal_prob"].get(team_name, 0),
            "finalist_prob": results["finalist_prob"].get(team_name, 0),
            "winner_prob": results["winner_prob"].get(team_name, 0),
        })

    if name == "get_fixtures":
        group_filter = (inputs.get("group_name") or "").upper().strip()
        team_filter = inputs.get("team_name") or ""
        round_filter = (inputs.get("round") or "").lower().strip()

        out = []

        if round_filter != "knockout":
            fixtures_by_group = results.get("fixtures", {})
            for g in engine.groups:
                if group_filter and g["name"] != group_filter:
                    continue
                for m in fixtures_by_group.get(g["name"], []):
                    if team_filter and team_filter not in (m.get("home"), m.get("away")):
                        continue
                    nm = normalize_group_match(m)
                    nm["group"] = g["name"]
                    nm["sort_key"] = utc_sort_key(m).isoformat()
                    out.append(nm)

        if round_filter != "group" and not group_filter:
            bm = results.get("bracket_matches", {})
            for mdef in engine.all_knockout_defs:
                match = bm[mdef["match"]]
                if team_filter:
                    home, away = match.get("home", {}), match.get("away", {})
                    teams = {home.get("team"), away.get("team")}
                    if team_filter not in teams:
                        continue
                nm = normalize_bracket_match(match)
                nm["sort_key"] = utc_sort_key(match).isoformat()
                out.append(nm)

        out.sort(key=lambda f: f["sort_key"])
        return json.dumps(out)

    if name == "get_group_stats":
        group_name = inputs.get("group_name", "").upper()
        group = next((g for g in engine.groups if g["name"] == group_name), None)
        if group is None:
            return json.dumps({"error": f"Group '{group_name}' not found."})
        teams = []
        for tname in group["teams"]:
            tidx = engine.team_idx[tname]
            team_data = engine.data["teams"][tidx]
            teams.append({
                "name": tname,
                "elo": team_data["elo"],
                "advance_prob": results["group_advance_prob"].get(tname, 0),
                "winner_prob": results["winner_prob"].get(tname, 0),
            })
        return json.dumps({"group": group_name, "teams": teams})

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a football analytics assistant for the 2026 FIFA World Cup.
You have access to Monte Carlo simulation results (tens of thousands of simulated tournaments).
Use the available tools to fetch the statistics needed to answer the user's question accurately.
Use get_fixtures for questions about specific matches, schedules, kickoff times, venues, or results.
Be concise, cite specific probabilities, and express them as percentages.
The simulation uses Elo-based Poisson goal models for every individual match (group stage and
knockout). Group stage: 12 groups of 4, top 2 plus the 8 best third-placed teams advance.
Knockout stage uses the official FIFA bracket. Draws in knockout rounds go to penalties."""


def answer_question(
    question: str,
    engine: Any,
    results: dict | None,
    user_settings: dict | None = None,
    history: list[dict] | None = None,
) -> str:
    if results is None:
        return "No simulation results are available yet. Please run a simulation first (see the Simulations page)."

    api_key, model = _get_config(user_settings)
    if not api_key:
        return ("No OpenRouter API key configured. Add one on the Settings page "
                "(or set the OPENROUTER_API_KEY environment variable).")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Prior turns of the conversation, so follow-up questions ("what about
    # for Brazil instead?") have context. Only plain user/assistant text
    # turns are accepted — tool-call messages from earlier turns aren't
    # replayed.
    for msg in (history or []):
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question})

    # Agentic loop: let the model call tools until it produces a final answer
    for _ in range(5):
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "tools": TOOLS,
                    "max_tokens": 1024,
                },
                timeout=60,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            return f"OpenRouter request failed: {e}"

        data = resp.json()
        if "error" in data:
            return f"OpenRouter error: {data['error'].get('message', data['error'])}"

        choice = data["choices"][0]
        message = choice["message"]
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            return message.get("content") or "Unable to generate an answer."

        messages.append(message)
        for call in tool_calls:
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _execute_tool(fn["name"], args, engine, results)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": result,
            })

    return "Unable to generate an answer."
