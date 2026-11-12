# Brief: one section of the CC Sync feature inventory

You are writing ONE section of a feature inventory. The owner of this
software believes it has become bloated and wants a briefing document for a
full rebuild from scratch: a perfectly granular list of everything the
software DOES, so that (a) a new team could rebuild it without ever reading
this code, and (b) the owner can go down the list and decide what to cut.
Your prompt names the files that are your part and the file you write.

## The rules

1. **The executable code is the only source of truth.** Do NOT trust `docs/`,
   any README, `CLAUDE.md`, `SPEC.md`, `KNOWN_BUGS.md`, docstrings or
   comments: they may be stale, or describe an intention that was never
   built. A comment is at most a hint about where to look; confirm it in the
   code that runs before you write it down. Where a comment or docstring
   claims something the code does not do, write what the code does, and add
   the mismatch to the "Claims the code does not back" list at the end.
   Tests may be read as evidence of behaviour, but list only what the shipped
   code does.

2. **Read every file in your part completely.** Large files in chunks, start
   to end. Do not sample, do not skim, do not infer a feature from a function
   name. If you run short of room, say exactly which files or line ranges you
   did not read; never paper over it.

3. **Features, not architecture.** Describe behaviour as it is seen from
   outside: what a person can see, press, type or drag; what a machine does on
   its own, when, under which conditions, with which limits. Do NOT describe
   modules, classes, call graphs, threads, locks, data structures, frameworks,
   storage layout, or why something was built the way it was. No file layout.
   No history. The one exception: after each group heading put a short source
   tag like `(source: lane_guard.py)` so a claim can be checked.

4. **Granularity: one bullet per distinct behaviour.** In particular, list:
   - every HTTP route: method, path, who may call it, what it does, every
     refusal and its condition;
   - every page, window, dialog, tray or menu item, and every control on it,
     with what it does;
   - every keyboard shortcut, controller button, stick, trigger, mouse and
     touch gesture, with exactly what it does in each context (tap versus
     hold, with and without modifiers);
   - every setting, config key, environment variable and command-line flag:
     its default and its effect;
   - every background task: what triggers it, how often, what it does;
   - every notification, alert, warning and error a person can be shown, and
     the condition that shows it (quote short user-visible strings exactly);
   - every file or folder the feature creates, reads or moves that a user or
     operator would know about;
   - every number: timeouts, sizes, intervals, retry counts, retention;
   - every state a thing can be in and what moves it between states;
   - every refusal and the condition for it;
   - every difference between Windows, macOS and Linux;
   - every feature flag and exactly what it gates.
   Include features that are off by default, dev-only hatches, and features
   that are present but cannot be reached. Mark them `DORMANT`, `DEV ONLY` or
   `UNREACHABLE: <why>`.

5. **End your section with three short lists:**
   - `## Looks redundant or overlapping`: features in your part that duplicate
     each other, or duplicate another surface you noticed. Facts only.
   - `## Claims the code does not back`: see rule 1.
   - `## Could not determine`: anything you could not settle from the code.

6. **Plain language.** Define a term the first time you use it. Full
   sentences or clear phrases, not shorthand. No em dashes.

7. **Output.** Write your section as ONE Markdown file at the path your
   prompt gives. Shape: `# <section title>`, then `## <feature area>` with its
   source tag, then nested bullets. No introduction essay, no summary of how
   you worked. Length is not limited: completeness beats brevity, and a
   section of several thousand lines is fine. For a long section, write the
   file in several appends rather than one giant write, so nothing is lost.
   Before you finish, list the files of your part and check that each one is
   represented in what you wrote.

8. **Touch nothing else.** Do not modify, create or delete any other file in
   any repo. Do not run tests, builds or the app. Do not commit. Other work is
   going on in these working trees at the same time.

## Your final reply

Keep it short: the path you wrote; roughly how many feature bullets; which
files you read in full and which only in part (be exact and honest); and the
five things in your part that most look like bloat, one line each.
