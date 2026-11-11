# context-alert

A Claude Code hook that stops you when a conversation gets expensive.

[עברית](README.he.md)

## The problem

The cost of a Claude Code conversation is its size and its lifetime, not the size of the task.

- Every step re-reads the whole conversation from the prompt cache. A small edit at 400K tokens costs several times the same edit in a fresh conversation.
- The prompt cache expires. Come back to a big conversation after a break and the whole thing is written into the cache again, at full price.
- Nothing tells you when it happens. You find out from the bill, or when the weekly limit runs out mid-week.

We measured one week of our own work: 39 of 49 conversations passed 200K tokens, and 13 passed 500K. Ordinary conversations cost nine times more than all our scheduled automations together.

## What it does

It reads the real size of the conversation from the transcript and, at the right moment, makes Claude stop and ask you:

1. **Fresh session with a handover (recommended).** Claude writes a full handover and the work continues in a new conversation.
2. **Condense here.** You run `/compact`.
3. **Continue as is.** This level will not ask again.

It fires:

- when the conversation passes 100K, 200K and 400K tokens, once per level;
- when you come back after an hour or more to a conversation of 100K tokens or more.

After `/compact` or `/clear` the levels re-arm. On any error the hook exits silently, so it can never block your work. It sends nothing anywhere: one Python file, standard library only, reading a local file.

## Install

Requires Claude Code and Python 3.8 or later. Works in the terminal, the desktop app and cloud sessions. It does not work in the claude.ai chat, which has no hooks.

### As a plugin (recommended)

Inside Claude Code:

```
/plugin marketplace add niroavra/claude-context-alert
/plugin install context-alert@nirox
```

### By hand

1. Copy `scripts/context-alert.py` to `~/.claude/hooks/context-alert.py`.
2. Merge `settings-snippet.json` into `~/.claude/settings.json` (all projects) or into `.claude/settings.json` in one project.

For cloud sessions, use the project route: commit the script into the repository, for example at `.claude/hooks/context-alert.py`, and point the two commands in `.claude/settings.json` at `"$CLAUDE_PROJECT_DIR/.claude/hooks/context-alert.py"`.

On Windows, replace `python3` with `python` in the command if that is how Python is installed.

## Settings

All optional, as environment variables (the `env` block of `settings.json` works).

| Variable | Default | Meaning |
|---|---|---|
| `CONTEXT_ALERT_LEVELS` | `100000,200000,400000` | Token levels that trigger the alert |
| `CONTEXT_ALERT_COLD_MIN` | `60` | Minutes away that count as a cold return |
| `CONTEXT_ALERT_COLD_TOKENS` | `100000` | Smallest conversation worth a cold alert |
| `CONTEXT_ALERT_LANG` | `en` | Language of the one-line notice: `en` or `he` |

The question itself is asked in the language you write in.

Which levels fit you: on a model with a 200K context window only the 100K level and the cold return can fire, because Claude Code condenses the conversation before 200K. On a 1M window all three matter. If the 100K stop is too early for you, set `CONTEXT_ALERT_LEVELS=200000,400000`.

## Bonus: a ceiling on the conversation

On a 1M context window, Claude Code condenses the conversation on its own only when the window is nearly full. One environment variable lowers that ceiling:

```
CLAUDE_CODE_AUTO_COMPACT_WINDOW=400000
```

For cloud sessions, set it in the environment's settings (it cannot be set from inside a conversation). In the terminal, put it in the `env` block of `~/.claude/settings.json`. We run it in our cloud environments: conversations there condense at about 350K.

The alert and the ceiling work together. The alert asks you at the moment a choice is cheap. The ceiling catches the conversations where nobody was there to answer.

## Uninstall

Plugin: `/plugin uninstall context-alert@nirox`. By hand: remove the two hook entries from `settings.json` and delete the script. The state folder is `~/.claude/context-alert`.

## License

MIT. Built by [NiroX](https://nirox.io), where we build AI workforces for small businesses.
