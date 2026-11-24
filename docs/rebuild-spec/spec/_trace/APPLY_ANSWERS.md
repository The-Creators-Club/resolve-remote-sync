# Applying the owner's answers to a piece of the specification

Stays behind. Written 2026-11-24, for the writers of the 27 pieces.

The owner has answered the decision list. Unless your message names an
exception, **he accepted every recommendation in your trace's "Questions
for the owner"** (his words, of everything still waiting: "accept all the
recommendations"). Your piece now has to say what he decided, with nothing
left hanging on those questions.

## What to do

For each question in your trace's "Questions for the owner":

1. **Make the text say the recommended option** (or the option your message
   names as his own choice). Your text was mostly written to the
   recommendation already; check that every passage really does say it.
2. **Where you recommended cutting something and kept the passage "ready to
   delete", delete it now**, with its settings lines, its ways in and any
   mention of it elsewhere in your piece. Where you recommended one place
   for something that could be done from several, the `- Ways in:` line
   keeps only the places that stay.
3. **Remove every `- Pending:` mark that rests on that question.**
4. **In the trace, add to the question** a line
   `- Answered by the owner 2026-11-24: <the option he chose, in a few words>`.
   Do not delete or renumber questions.
5. Where an answer goes against a lesson of kind `ruling`, his answer of
   2026-11-24 is the later word: write it, and log the conflict in the
   trace. A lesson you no longer meet because of his answer is listed
   under "Not yet met" with "(the owner's answer of 2026-11-24)".
6. Coverage lines for items whose passage you deleted become
   `left out: cut by the owner (2026-11-24, <question id>)`.

## Decisions of his that reach every piece

- **The assistant is called "Assistant" on screen**, never by a maker's or
  model's name. Wherever your text has `[the assistant]` inside on-screen
  wording, write `Assistant` ("Ask Assistant"). Where a person chooses how
  strong it answers, each choice is named by what it does (fastest,
  stronger, most capable) with its price. Other bracketed roles
  (`[speech-to-text]`, `[the episode's media]`) stay as they are.
- **A new site starts with every one of the six switchable parts off,
  except the help for the editing program.** If your piece states a part's
  default, it is off (the help for the editing program: on).
- **Making proxies is on by default on every computer.**
- **One Footage Sorter and one Timeline Cards, both inside the dashboard,
  behind its sign-in.** The stand-alone forms are gone.
- **Tools that exist only for the people building the product are left
  out.**
- **The subscription way of running the assistant stays**, off by default
  on every new site, switched on in one place only: by accepting the
  notice inside the set-up. A paid key remains the usual way.
- **Everything the Footage Sorter offers is usable by touch.**
- **The Footage Sorter moves sorted originals on its own, with no
  approval**; a person overrules by hand afterwards.
- **A project ticked "upload only" brings its empty folders down**, and
  nothing else.
- Read `E:\Projects\Editing\ccsync\docs\rebuild-spec\spec\OWNER_REQUIREMENTS.md`
  again: it gained the language, the measuring of how footage travels, the
  new-site defaults and the assistant's name.

## Points that were "still unsettled"

Your message says which of yours he has now settled and how. For each:
write it into the text, remove its `- Pending:` mark, delete its line under
"Still unsettled", and add it under a section `## Settled by the owner
2026-11-24` at the end of the trace as `- <id> | <what he decided>`. A
point your message does not mention stays as it is.

## Rules that have not changed

- The text has no past: never "used to", "no longer", "was removed", "the
  owner decided". It simply says what the product does.
- Describe the job, not the arrangement. Exact text stays exact, except the
  assistant's name as above.
- Touch only your two files. Do not commit. Do not start sub-agents.
- Run `python E:\Projects\Editing\ccsync\docs\rebuild-spec\tools\check_spec.py <piece>`
  until it prints `OK`.

## Your reply

Three to six lines: how many questions you applied, how many passages you
deleted and which, how many `- Pending:` marks are left and what each
still rests on, and anything in his answers that contradicts another part
of your piece or that you could not apply.
