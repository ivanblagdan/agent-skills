# agent-skills

Reusable agent skills by [ivanblagdan](https://github.com/ivanblagdan).

## Skills

- `lldb-debugging` — inspect an active Xcode LLDB session through a local Unix socket bridge, so an agent can request stacks, frame variables, expressions, and memory reads.

## Install

Install with [vercel-labs/skills](https://github.com/vercel-labs/skills):

```bash
npx skills add ivanblagdan/agent-skills --skill lldb-debugging
```

Install for Pi specifically:

```bash
npx skills add ivanblagdan/agent-skills --skill lldb-debugging -a pi
```

Or install the skill directly by path:

```bash
npx skills add https://github.com/ivanblagdan/agent-skills/tree/main/skills/lldb-debugging
```

## Notes

- Review skills before installing them.
- `lldb-debugging` includes Python scripts that run locally.
- The LLDB bridge is intended for trusted local debugging workflows on macOS with Xcode.
