---
name: mindera-slack-access
description: Search and read Mindera's Slack workspace using the `slackcli` CLI tool. Use when asked to find past conversations, look up decisions, or research what was discussed about a topic in Slack. This is separate from any native Slack plugin used for real-time messaging — this skill is for searching historical Slack content.
metadata: { "openclaw": { "emoji": "💬", "requires": { "bins": ["slackcli"] } } }
---

# Mindera Slack — `slackcli`

## What this is (and is not)

This skill searches and reads **historical content** in Mindera's Slack workspace
using the `slackcli` CLI binary. It is for finding past conversations, looking up
decisions, and researching what was discussed about a topic.

This is **separate from** any native Slack integration (e.g. OpenClaw's Slack plugin)
used for real-time messaging and channel participation. That integration posts and
receives messages in real time; this skill reads the archive.

## Binary and auth

| | |
|---|---|
| Binary | `/usr/local/bin/slackcli` |
| Auth tokens | `~/.config/slackcli/` (bind-mounted from host, read-write) |
| Workspace name | `mindera` |
| Workspace ID | `T02DR2M61` |

Authentication is browser-based. The token directory is mounted from the host so
that a login performed on the host persists into the container.

## ⚠️ Auth errors and token refresh

Token refresh may fail inside Docker if the container UID does not match the host
UID that created the token files. If commands fail with authentication errors:

1. **Do not retry in a loop.** The token is invalid, not intermittent.
2. **Do not attempt to re-authenticate inside the container.** The browser flow
   requires the host.
3. **Tell the operator plainly:** the host-side `slackcli` needs to re-authenticate.
   The operator runs `slackcli auth login --workspace mindera` on the host, and the
   refreshed token is picked up via the bind mount.

Check auth before doing anything else:

```bash
slackcli auth status --workspace mindera
```

## Key commands

### Search messages

```bash
slackcli search messages --workspace mindera --query "search term"
```

### Search files

```bash
slackcli search files --workspace mindera --query "search term"
```

### List channels

```bash
slackcli conversations list --workspace mindera
```

### Read channel history

```bash
slackcli conversations history --workspace mindera --channel CHANNEL_ID
```

### List users

```bash
slackcli users list --workspace mindera
```

## When to use this skill

- Finding past conversations about a topic
- Looking up decisions that were made in Slack
- Researching what was discussed about a project, incident, or proposal
- Finding files shared in Slack channels
- Identifying who was involved in a discussion

## When NOT to use this skill

- Sending messages (use the native Slack integration for that)
- Real-time channel participation
- Creating channels or managing workspace settings

## Safety

- Slack messages may contain sensitive information, internal discussions, or personal
  conversations. Do not expose message content to contexts where it does not belong.
- Do not enumerate entire channels or workspaces "to see what is there". Search for
  what was asked for.
- Treat DMs and private channels with extra care if they appear in results.
- Never print auth tokens or the contents of the config directory.
