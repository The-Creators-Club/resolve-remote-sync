# Decision list, page 3: The whole product

Stays behind: never shown to the session that rebuilds the product.

10 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 3.1 Should what the server notices when it starts be shown to admins on the list of problems?

- **Today:** when it starts the server notices some things that will stop people working (a person listed as an admin with no account, NAS details missing so editors cannot sign in) and only writes them to its own log, which nobody reads.
- **Options:** A: raise each on the overview's list of problems, with what to do. B: keep them in the log only.
- **Recommended:** A, since the rule everywhere else is that nothing fails silently and these break sign-in.
- **What you would notice:** with A an admin sees, on the overview, that editors cannot sign in and why, instead of hearing it from an editor.
- (whole-product-Q2)

### 3.2 Should every "are you sure" question be the same dialog, with the same buttons?

- **Today:** most questions appear in the product's own dialog titled "are you sure" with Cancel focused and "Yes, do it"; a few (signing out everywhere) use the browser's own plain box with OK and Cancel; music's questions say Cancel and "Go ahead".
- **Options:** A: one dialog of the product's own everywhere, titled "Are you sure?", Cancel focused, "Yes, do it". B: keep the mix.
- **Recommended:** A, one way to ask is fewer parts and a person always knows which button is safe.
- **What you would notice:** signing out everywhere and music's questions look and read like every other question.
- (whole-product-Q3)

### 3.3 Should the installed Timeline Cards app keep its own icon (rows with a red playhead), or carry the product's mark like every other window?

- **Today:** every icon of the product comes from one brand mark, except the installed Timeline Cards app, whose icon is rows on a dark rounded square with a red playhead. Your ruling puts the maker's mark on every window, popup, installer, taskbar entry and tab.
- **Options:** A: the installed Timeline Cards app uses the product's mark like everything else. B: it keeps its own rows-and-playhead icon.
- **Recommended:** A, since your ruling asks for one mark everywhere and a studio's own logo should reach this icon too.
- **What you would notice:** with A the Timeline Cards app on a phone or computer shows the same mark as the rest of the product (or the studio's logo).
- (whole-product-Q5)

### 3.4 Should a site be able to connect several kinds of assistant, in an order with a pin, or just one?

- **Today:** an admin can set up several assistant services, tried in a fixed order unless one is pinned; but Timeline Cards' assistant features work with only one kind, so any other kind leaves them refused, and some kinds answer only YouTube search.
- **Options:** A: keep several kinds, the order and the pin. B: one kind of assistant only, the one every feature works with, connected with one key.
- **Recommended:** A, since it keeps the studio free to choose and change the assistant's maker, as the product is kept free of any one editing program; B is the fewer-parts choice if you are content to tie every feature to one maker.
- **What you would notice:** with B an admin pastes one key and everything works; with A an admin can mix kinds but may find Timeline Cards refusing.
- (whole-product-Q6)

### 3.5 Should naming gear from a photo for the studio's website follow the site's assistant choice and the switch that turns the assistant off?

- **Today:** the studio's public website can send the server a photo of gear and get a packing-list entry back; unlike every other use of the assistant, it always uses the subscription program and ignores the admin's choice, the pin and the site's switches.
- **Options:** A: it follows the site's choice, pin and switch like everything else. B: it keeps its own fixed way. C: cut it from the product; it serves the website, not editing.
- **Recommended:** A, one way to reach the assistant; C if the website can call an assistant itself.
- **What you would notice:** with A, switching the assistant off also stops gear naming; with C the website's gear page loses the photo button.
- (whole-product-Q8)

### 3.6 Two limits on assistant spending stack: a spend per hour and a number of calls per day. Keep one, both, or neither?

- **Today:** the person running the server can set a dollar limit per rolling hour and, separately, a count of assistant calls per day; both are off by default and both apply on top of each other. Your ruling also asks that routine runs stay within a cost you set.
- **Options:** A: one limit, money per day, shown in settings, with the expected cost shown before each task. B: keep both as they are. C: neither, the key's own limit on the maker's side is enough.
- **Recommended:** A, one limit in the unit you think in (money) covers both and matches your cents-not-dollars ruling.
- **What you would notice:** with A an admin sets one daily budget; with B two.
- (whole-product-Q9)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 3.7 | Can the tools that exist only for the people building the product go? | four things exist only for building and testing: a switch that swaps the tray icon for another way of drawing it and logs every window that closes; a setting that lets any page served from the editor's own computer drive the app; a way for the server, run in its insecure development mode, to accept check-ins with no credentials; and a stand-in assistant for tests that never touches the network. | A, since nobody using the product meets any of them, and the one with a promise inside it (tests can never reach the real assistant) is a matter for the builders. (whole-product-Q1) |
| 3.8 | Should one computer be able to carry a different logo from the rest of the studio? | a logo can be set for the whole studio, and also given to one computer, where it wins over the studio's. | A, since one place a setting comes from is the owner's rule and nobody has needed a different logo on one machine. (whole-product-Q4) |
| 3.9 | Should a site be able to run the assistant through a personal subscription signed in on the server, or with a paid key only? | besides a paid key, an admin can fetch the assistant maker's own program onto the server and sign it in with a personal subscription, after accepting a notice that this may breach the subscription's terms; the server can keep that program up to date once a day. It is off on every new site, and the build sent to customers locks it off whatever is stored. Your rulings say every studio gets the same one build, and that customer builds use only the site's own paid key with no setting that enables subscription sign-in. | A, since one build serves every studio and your ruling forbids it for customers, so keeping it would mean a second build or breaking the ruling; it also removes a wizard, a sign-in, an updater and three warnings. (whole-product-Q7) |
| 3.10 | If the subscription way stays, where is it switched on: the tick box under the list, the notice in the set-up, the site's settings, or all three? | the site-wide switch allowing subscription programs can be set from a tick box under the list of assistants, by accepting the notice inside the set-up steps, and from the site settings form. | A, since accepting the notice is the one act that should turn it on, and one place is the owner's rule. (whole-product-Q10) |

## Your answers

ANSWERED 2026-11-24, asked one by one.

- 3.1 to 3.6: the recommendation each time. Start-up findings go on the
  problems list; one "Are you sure?" dialog everywhere; the installed
  Timeline Cards app carries the product's mark; a site may connect several
  kinds of assistant, with a pin; gear naming follows the site's assistant
  choice and its off switch; one daily budget in money, with the expected
  cost shown before each task.
- 3.9: **against the recommendation.** The subscription way of running the
  assistant STAYS in the product, off by default on every new site. (His
  own studio uses it.) This is later than, and overrules, the earlier
  ruling that a customer's build never offers it.
- 3.10: follows from 3.9 as recommended: it is switched on in one place
  only, by accepting the notice in the set-up.
- 3.7 and 3.8 (the builders' tools go; one logo for the whole studio): put
  to him as a tick-what-you-disagree-with list, which came back with
  nothing ticked. Taken as the recommendation; confirmed with him in the
  next round.
