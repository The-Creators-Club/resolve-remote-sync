# Brief: one lesson, one home (the pass across capabilities)

The knowledge base was merged one capability at a time, by agents who each
saw only their own capability. So a lesson that was filed under two
capabilities is still written twice, once in each. The owner's rule: "if
there are any lessons which are no longer relevant, or repeated lessons, or
superseded lessons, etc, they should all get removed from the final
document."

A script has laid side by side the finished entries, from different
capabilities, that read alike. It decided nothing. You rule on each group.
You do not rewrite anything: your whole output is one short file of rulings.

Read first, for the kinds (1a, 1b, 2, 3) and what a finished entry is:
`E:\Projects\Editing\ccsync\docs\rebuild-spec\knowledge-base\_parts\KB_MERGE_BRIEF.md`
(the sections "What you do with each entry" and "What the owner has cut or
decided"). Then read your batch completely.

In the batch, each entry's heading reads
`### <id> [<capability> / <sub-topic>]: <title>`.

## The rulings

One line per ruling, fields separated by ` | `, the group's number first.
Every group gets at least one line.

```
12 | distinct
13 | same | RSV-106 | CRX-008, CFI-041
13 | same | CFI-018 | RSV-111
14 | conflict | SYN-029 | DSH-077 | Does an upload-only project create its folders on the editor's disk?
```

- **`same | <keep> | <drop>, <drop>`**: these entries teach ONE rule: one
  test would catch all of them. The first id stays where it is; each
  dropped one is replaced, in its own capability, by a one-line pointer to
  the kept entry, so nothing is lost from either place. A group may have
  several `same` lines (two different repeats in one group); entries of the
  group you do not name stay as they are.
- **`distinct`**: every entry in the group is a different lesson. All stay.
- **`conflict | <id> | <id> | <question>`**: the two entries cannot both be
  true, or demand opposite things. Both stay; the question, in one plain
  sentence, is put to the owner. Do not pick a winner.

### When are two entries the same?

- Same, when one test would catch both and the kept entry loses nothing the
  rebuild needs: every number, limit, named situation and condition in the
  dropped entry is in the kept one, or is plainly implied by it.
- **Distinct, when each holds something the other lacks.** You cannot
  rewrite the kept entry, so if dropping one would lose a number, a second
  situation, or a condition, they are `distinct`. When in doubt, `distinct`:
  a rule said twice costs a line; a rule lost costs a bug found again.
- Distinct, when the same underlying fact is drawn out into two different
  rules for two different parts of the product (the fact about Resolve, and
  what the dashboard must show because of it).
- A general rule and a specific instance of it are distinct, unless the
  specific one adds nothing at all.

### Which one is kept?

1. The one that says more, more sharply (see above: it must lose nothing).
2. If they are equal, the one in the capability the lesson is really about:
   a fact about Resolve lives under `resolve-on-the-editors-computer`; a
   rule for every screen lives under `whole-product`; a fact about the
   editing computer's operating system under `editor-app`; and so on.
3. If still equal, the owner's ruling (kind 2) over a situation (kind 3).
4. An entry carrying `State:` or `Check:` may be dropped: those lines are
   carried over to the kept entry by the script.

Sealed entries (kind 1b, with a `Tool:` line) are only ever grouped with
other sealed entries. The same rules apply.

## The "marked to move" batch (`moves`)

A merger marked some entries as belonging to another capability. Each is a
group named `M<n>`: the marked entry, then the five entries of the target
capability that read most like it, then the target's sub-topics. Rule one
of:

```
M3 | move | <one of the target's sub-topics, copied exactly>
M4 | same | RSV-050 | APP-123
M5 | stay
```

- **`same | <an entry of the target> | <the marked entry>`**: the target
  already holds this lesson (same test as above). The marked entry is
  dropped in favour of it. Always `<target entry> | <marked entry>`, in that
  order.
- **`move | <sub-topic>`**: the lesson is not in the target yet and does
  belong there. Name the sub-topic it goes under.
- **`stay`**: the merger was wrong; it belongs where it is.

The five entries shown are a search result, not a judgement: usually none
of them is the same lesson.

## Your output

One file, at the path your prompt gives, holding only ruling lines (no
headings, no commentary; a line starting `#` is ignored). Then run

`python E:\Projects\Editing\ccsync\docs\rebuild-spec\tools\check_cross.py <batch name>`

and fix what it reports until it prints `OK`.

Touch nothing but that one file. Do not commit. Do not start sub-agents. A
temporary file's name must start with the prefix your prompt gives. Do not
read the product's code, the bug ledger, the register or the merged files:
everything you need is in your batch.

## Your final reply

Short: the path; how many groups, and how many `same`, `distinct`,
`conflict`, `move` and `stay` rulings; that the checker printed `OK`; and
every `conflict` question.
