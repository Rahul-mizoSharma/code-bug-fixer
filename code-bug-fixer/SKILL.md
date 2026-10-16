---
name: code-bug-fixer
description: Finds and fixes bugs in Python, FastAPI, JavaScript, React (JSX/TSX) and C# code the user supplies. Finds syntax errors and common runtime problems, explains the root cause, and returns corrected code. Use when a user asks to debug, review, fix, or explain an error in code in these languages. If the user hasn't supplied code yet, ask for it first and don't run any analysis.
---

# Code Bug Fixer

Finds and fixes bugs in **Python, FastAPI, JavaScript, React and C#** code.

## Step 0: Make sure you have the code (required)

Before you do anything else, check whether the user has given you code. Code can come as a pasted snippet, an uploaded file in `/app/uploads/`, or a file path.

- **If there's no code**, don't run `scripts/analyze.py` and don't guess. Reply with one short request, for example:
  > Please paste the code you want me to check, or upload the file. If you can, also include:
  > 1. The language/framework (Python, FastAPI, JavaScript, React, C#)
  > 2. The error message or stack trace, if there is one
  > 3. What the code should do and what it does instead
- If the user only describes a bug ("my React page loops forever"), still ask for the code. Don't invent a sample and analyze it.
- Run the script only after real code is available. The script also enforces this: if its input is empty, it exits with code `2` and prints `NO_CODE_PROVIDED`.

## Step 1: Save the code and run the static analyzer

Save pasted code to a scratch file with the right extension (`.py`, `.js`, `.jsx`, `.tsx`, `.cs`). Then run:

```bash
python3 scripts/analyze.py --file /app/workspace/snippet.py            # auto-detect language
python3 scripts/analyze.py --file app.py --lang fastapi                  # force a language
python3 scripts/analyze.py --file Comp.jsx --lang react --format json    # machine-readable output
cat code.cs | python3 scripts/analyze.py --stdin --lang csharp
```

`--lang` accepts `auto|python|fastapi|javascript|react|csharp`. The analyzer:
- **Python/FastAPI** checks syntax with `ast` and runs AST-based runtime and bug rules.
- **JavaScript** checks syntax with `node --check` when Node is installed, then applies heuristic rules.
- **React/JSX** uses a bracket and JSX balance check, plus rules for hooks, keys, effects and state.
- **C#** uses a bracket balance check and statement heuristics. It also runs `dotnet build` when the `.NET` SDK is installed and you pass `--compile`.

Each finding includes `line`, `severity` (`error|warning|info`), `category` (`syntax|runtime|logic|performance|security|style`), `rule`, `message` and `fix_hint`.

> The analyzer only gives you **leads**. You still need to read the whole code yourself. It can report false positives and won't catch every bug, especially logic errors. Confirm each finding before you report it, and look for problems the script can't see.

## Step 2: Do your own review

Using `references/bug_patterns.md` as a checklist, look for:
1. **Syntax errors.** Fix these first, because they hide everything else.
2. **Runtime errors.** Examples: null/None/undefined access, type mismatches, missing `await`, unhandled exceptions, index/key errors, deadlocks, infinite render loops.
3. **Logic errors.** Examples: off-by-one, wrong comparison, mutated shared state, wrong dependency arrays.
4. If the user gave a stack trace or error message, connect it to the exact line that causes it.

## Step 3: Write the response in this format

```
## Summary
<1–2 sentences: what's wrong overall>

## Issues found
| # | Line | Severity | Type | Issue |
|---|------|----------|------|-------|
| 1 | 12   | Error    | Syntax | Missing closing parenthesis |

## Root cause analysis
### Issue 1: <title>
- **What happens:** <the symptom or error the user sees>
- **Why:** <the underlying cause in plain language>
- **Fix:** <what to change>

## Corrected code
```<lang>
<complete corrected code that can run, not just a diff, unless the file is very large>
```

## What changed
- <short list of each change, tied to an issue number>

## Prevention tips (optional, max 3)
```

Rules for the corrected code:
- Keep the user's structure, names and style. Fix the bugs and don't rewrite anything unrelated.
- Mark each change with a short comment, for example `# FIX 1:`, `// FIX 2:`.
- Don't add new dependencies unless the fix needs them, and say so if you do.
- If you're not sure about a fix because context is missing (for example, an unknown type or a missing import), say so and state the assumption you made.
- If you find no bugs, say so clearly, and mention any risky patterns as optional improvements.

## Files
- `scripts/analyze.py`: static analyzer that needs only the standard library. Run it only after the user has provided code.
- `references/bug_patterns.md`: per-language checklist of common bugs and their standard fixes.
