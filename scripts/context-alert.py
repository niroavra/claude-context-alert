#!/usr/bin/env python3
"""context-alert: a Claude Code hook that stops you when a conversation gets expensive.

Why: the cost of a conversation is its size and its lifetime, not the size of the task. Every step
re-reads the whole conversation from the prompt cache, and a return after the cache expired writes
all of it again. Claude Code shows the size if you look for it, but nothing says "now is the time
to cut". This hook says it, inside the conversation, in the terminal and in cloud sessions.

How: it reads the real size from the transcript (the last main-thread answer's input + cache read +
cache write tokens) and tells the agent, through additionalContext, to stop and ask you with three
choices: a fresh session that starts from a handover (recommended), /compact here, or continue.

  UserPromptSubmit: the size levels, and the cold return (idle COLD_MIN minutes at COLD_TOKENS or more).
  PostToolUse:      the size levels only, so a long autonomous turn that crosses a level is caught mid-way.

Each level fires once per conversation. When the conversation drops back under the lowest level
(/compact, /clear), the levels re-arm. Any error exits 0 silently: this hook never blocks work.

Settings (environment variables, all optional):
  CONTEXT_ALERT_LEVELS       token levels, comma separated      default "100000,200000,400000"
  CONTEXT_ALERT_COLD_MIN     minutes away that count as cold    default 60
  CONTEXT_ALERT_COLD_TOKENS  smallest conversation worth a cold alert   default 100000
  CONTEXT_ALERT_LANG         language of the one-line notice: en or he   default en
  CONTEXT_ALERT_STATE_DIR    where the per-conversation state is kept    default ~/.claude/context-alert

By NiroX (https://nirox.io). MIT license.
"""
import json
import os
import sys
from datetime import datetime, timezone

LEVELS = sorted(int(x) for x in os.environ.get("CONTEXT_ALERT_LEVELS", "100000,200000,400000").split(","))
COLD_MIN = int(os.environ.get("CONTEXT_ALERT_COLD_MIN", "60"))
COLD_TOKENS = int(os.environ.get("CONTEXT_ALERT_COLD_TOKENS", "100000"))
LANG = os.environ.get("CONTEXT_ALERT_LANG", "en").lower()
STATE_DIR = os.environ.get("CONTEXT_ALERT_STATE_DIR", os.path.expanduser("~/.claude/context-alert"))
TAIL_BYTES = 4 * 1024 * 1024

NOTE = {
    "en": ("Context alert: {size} tokens", " · back to a cold conversation"),
    "he": ("התראת שיחה: {size} טוקנים", " · חזרה לשיחה קרה"),
}


def k(n: int) -> str:
    return f"{round(n / 1000)}K"


def last_answer(path: str):
    """(tokens, epoch seconds) of the last main-thread assistant entry, or None."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        if '"assistant"' not in line or '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        u = (d.get("message") or {}).get("usage") or {}
        tokens = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (
            u.get("cache_creation_input_tokens") or 0
        )
        if not tokens:
            continue
        ts = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp()
        return tokens, ts
    return None


def load_state(session: str) -> dict:
    try:
        with open(os.path.join(STATE_DIR, f"{session}.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"warned": []}


def save_state(session: str, state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, f"{session}.json"), "w") as f:
        json.dump(state, f)


ASK = (
    "Ask in the language the user has been writing in, with the facts above in the question. Use the "
    "AskUserQuestion tool if you have it (one question, short header such as \"Heavy conversation\"); "
    "otherwise ask in plain text. Offer these three options, in this order:\n"
    "1. \"Fresh session with a handover (recommended)\": you write a handover and the work continues in a "
    "new conversation.\n"
    "2. \"Condense here (/compact)\": the same conversation, condensed. Only the user can run it: tell them "
    "to type /compact, with a focus if one matters (e.g. /compact keep the decisions about X).\n"
    "3. \"Continue as is\": continue; this level will not ask again.\n"
    "If they pick 1: commit any open work if the project uses git (push only if that is how this session "
    "already works); then write the handover in full: the goal, the decisions taken, what is done with "
    "file paths, what is open, the exact next step, the branch. If you have a tool that opens a new session "
    "(for example create_session in a Claude Code cloud session), open one with the whole handover text as "
    "its prompt and give the user the link. Otherwise print the handover in one code block and tell the user "
    "to type /clear (or open a new session) and paste it as the first message."
)


def main() -> None:
    data = json.load(sys.stdin)
    event = data.get("hook_event_name", "")
    session = data.get("session_id") or "unknown"
    path = data.get("transcript_path") or ""
    if event not in ("UserPromptSubmit", "PostToolUse") or not os.path.isfile(path):
        return
    found = last_answer(path)
    if not found:
        return
    tokens, last_ts = found

    state = load_state(session)
    warned = set(state.get("warned", []))
    if tokens < LEVELS[0] and warned:
        warned = set()  # condensed or cleared: re-arm the levels

    facts = []
    crossed = [lv for lv in LEVELS if tokens >= lv and lv not in warned]
    if crossed:
        facts.append(
            f"This conversation is now {k(tokens)} tokens, past the {k(max(crossed))} level. Every step re-reads "
            f"all of it from the cache, so each one costs several times a step in a fresh conversation."
        )
        warned.update(lv for lv in LEVELS if lv <= tokens)

    cold = False
    if event == "UserPromptSubmit":
        idle = (datetime.now(timezone.utc).timestamp() - last_ts) / 60
        if idle >= COLD_MIN and tokens >= COLD_TOKENS:
            cold = True
            facts.append(
                f"The user came back after {round(idle)} minutes: the prompt cache has most likely expired, so "
                f"this turn writes all {k(tokens)} tokens into the cache again, and so will every later cold return."
            )

    if sorted(warned) != state.get("warned"):
        state["warned"] = sorted(warned)
        save_state(session, state)
    if not facts:
        return

    when = (
        "Before working on the user's message"
        if event == "UserPromptSubmit"
        else "Finish the step you are in (never leave a half-made change), then before the next one"
    )
    context = "[context-alert] " + " ".join(facts) + f"\n{when}, stop and ask. " + ASK
    head, cold_tail = NOTE.get(LANG, NOTE["en"])
    print(
        json.dumps(
            {
                "systemMessage": head.format(size=k(tokens)) + (cold_tail if cold else ""),
                "hookSpecificOutput": {"hookEventName": event, "additionalContext": context},
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001  never block a turn
        pass
    sys.exit(0)
