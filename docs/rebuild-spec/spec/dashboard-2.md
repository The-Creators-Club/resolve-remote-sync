# The dashboard, part 2 of 2

This part covers how the dashboard tells people about problems by mail, every setting of a site and how settings are saved, how its pages stay fresh and answer clicks, how fast it stays under load, how it behaves on phones and as an installed app, how its pages are kept safe, and how an admin stops and resumes syncing across the whole studio.

## Alerts by mail

### An admin chooses who is told when the server finds a problem

The server checks the whole studio on its own, about every 10 minutes, and an admin chooses where what it finds is sent: to nobody, by e-mail, or posted to the web address of another service (each message posted as a subject and a text). Nobody is the default. Any other choice is refused with a message naming the three that are allowed.

The alert settings open with: "Off by default. Nothing here ever leaves this NAS unless you set a channel. One save checks every field below together, and refuses the whole form on one bad field." Choosing nobody reads "Nothing leaves this NAS. Problems still show on the dashboard." With nobody chosen, problems are still found, still shown on the dashboard and still counted among the open problems; they are written down and nobody is told.

For e-mail the admin gives the outgoing mail server, its port (usually 587 with an upgraded secure connection, or 465), the sign-in name and password of the mail account, the sender address, and one or more recipient addresses separated by commas or semicolons. A port must be between 1 and 65535 ("must be a port number between 1 and 65535") and may be left blank. The connection is encrypted unless the admin turns that off; turning it off while a mail sign-in is set is refused, both when the settings are saved and again when a message is sent, and the admin is told that the mail password would cross unencrypted. The mail server's certificate and name are checked unless the admin turns that off, which is an explicit choice for a studio's own internal mail server with its own certificate. A certificate that fails the check is a refusal, never a quiet fallback to sending unchecked; the admin is told "the certificate <host> presented could not be verified (...). If this is your own mail server with its own certificate, turn off 'Verify the mail server's certificate' in the alert settings."

A web address for alerts must start with https://, or the save is refused: "the webhook URL must start with https:// (an alert body names your editors and computers)". It is checked again each time a message is sent. Because the rest of such an address works as a password, it is shown masked after its site part ("https://host/..."); saving the form back with the mask unchanged keeps the stored address. Only the site part is ever written into the list of what was sent. The server never follows a redirect from that address.

Every mail the product sends goes this one way: to the alert recipients, from the sender address, through these settings. That includes the daily footage-not-at-home mail (see The Footage Sorter and camera cards: Backed up and safe to format, "A report and a daily mail say what footage is not at home").

Saving answers "saved." or, when a destination was just switched on, "Saved. The next check will send everything that is currently open." Each save is recorded in the history of changes, naming the kind of destination only, never the address. None of these settings is ever handed to editors' computers or their installers.

- Who: an admin.
- Ways in: the alert settings, and the short "who should we tell" step of the setup checklist.
- Name and search words: Alerts. Search words: alerts, mail, e-mail, notify, webhook, warnings.

### The mail password is typed once and never shown back

The admin types the mail account's password. It is kept apart from every other setting and is readable only by the server. A blank password is refused ("the password is blank"), as is one over 400 characters, or one holding control characters ("the password contains control characters, paste it again"). Storing it answers "password stored."; if it cannot be stored, the admin is told what on the server must be made writable. Clearing it deletes it ("password cleared.", or "there was no stored password."). The page only ever shows whether a password is set and a mask of it: its first 3 and last 4 characters, or only "..." when it is under 12 characters long.

- Who: an admin.

### Setup asks who should be told when something goes wrong

One step of the setup checklist is "Who should we tell?" It is optional, with the button "SAVE A DESTINATION", and reads: "This server checks dozens of things about your fleet every few minutes. It needs somewhere to send what it finds. With nobody to tell, the first anyone hears of a stopped sync is an editor asking."

The admin gives one e-mail address (up to 320 characters, with an "@" not at either end) or one web address to post to (up to 1,024 characters), never both ("pick one: ..."), and may tick "Also send one short "still here" message a day. If they stop arriving, this server is down." (ticked here to start with). An e-mail address also becomes the sender when no sender is set. "Email is sent through the mail server set for alerts. If you have not set one up yet, save the address here and finish there." A "send a test" button sends "This is a test of the CC Sync alert channel. Nothing is wrong." even when one was just sent, and says where it went.

The step shows one of:

- "nobody is being told" (to do), asking for an e-mail address or a web address to post to;
- a warning when e-mail or posting was chosen without its address, when there is an address but no mail server ("fill in the mail server in the alert settings"), or when a mail account has no password;
- done, as "alerts go to <address> through <mail server>" or "alerts go to <masked web address>", adding whether the daily "still here" message is on, or that with it off nothing tells anyone if the server itself goes down.

An admin may also choose, on purpose, to tell nobody. That choice is recorded, ends the warning that nobody is being told, and the step then reads that nobody is told by the admin's own choice.

- Who: an admin.
- Ways in: the setup checklist, and the full alert settings.

### The dashboard says whether alerts are really reaching anyone

Alert delivery is shown as working only when a destination is set, something was delivered through it to someone in the last 30 days, and the most recent failure is older than the last success. This is the one rule for whether somebody is told, wherever the product says it. Green reads "the e-mail channel delivered something N hour(s) ago", naming the channel by what it is: e-mail or the other service. Otherwise it is shown as not working, with one of:

- "no mail server and no webhook is set, so nothing this server finds is ever sent to anybody";
- "the e-mail channel is set up and has never managed to send anything: ...";
- "the e-mail channel is set up but nothing has ever been sent through it";
- "the last message this server tried to send did not go out: ...";
- "nothing has been delivered through the e-mail channel since YYYY-MM-DD".

When the record of what was delivered cannot be read, the status line reads "cannot verify", never green.

After each check the server's status also says how many alerts were sent, that some could not be delivered, that the channel is slow ("S of T alert(s) sent this check; the alert channel is slow"), or, with no destination, "N alert(s) were written down here and nobody was told: no alert channel is set up".

While no destination is set, or nothing has been delivered through it in the last 30 days, a warning stands among the open problems: "Nobody is being told when this server finds a problem..." with the fix: set an address or a web address in the alert settings, then press "Send a test". An admin's recorded choice to tell nobody ends that warning, but the home page and the protection list still read that nobody is told, by the admin's own choice, and never show it as green.

- Who: an admin.
- Ways in: the alert channel's own status line beside the alert settings, and the standing problem among the open problems.

### An admin sends a test alert

"Send a test" sends "This is a test of the CC Sync alert channel. Nothing is wrong." through the saved destination, every time it is pressed, never held back as a repeat, and answers "test sent to <address>." or "the test could not be sent: <detail>". It is how an admin proves the channel works or times it. A test that goes through counts as a real delivery: it also clears the problem "the weekly report could not be sent".

- Who: an admin.
- Ways in: the alert settings, and the setup checklist's "who should we tell" step.

### An admin sees every problem open now and every kind of check

The problems open now, their severities (error, warning or information), their counts, the all-clear line and every check with whether it ran are the one list on the Overview (see The dashboard: Problems the server finds, "Everything the server knows is wrong is in one list" and "What the server checks, and whether each check ran"). What belongs to alerts by mail is shown with the alert settings:

- every kind of check, with its title, what it means and whether it sends a message;
- the alert settings, with a password shown only as set or not set and a mask;
- "Preview this week's report", which opens the subject and body of this week's report as plain text in a new tab, put together from what is open now; nothing is sent.

Inside a message, an error is headed "problem" and a warning "to look at".

- Who: an admin.

### An admin chooses which kinds of problem send a message

The kinds of check are listed with a tick each, under the words "So that silence is provably checked, not unchecked. Tick the kinds you want to be told about. An unticked kind is still checked every M minutes and still shows on this page and in the weekly report; it just sends no message. A check added in a later update starts ticked." "All", "Problems only" and "None" set the ticks at once; "Save" answers "saved. N of M kinds are sent as alerts." and "The rest are still checked and still shown on this page and in the weekly report." The save is recorded in the history of changes.

A switched-off kind is still checked, still shown among the open problems, in the weekly report and in the count of open problems; only its message is held back. Switching it back on sends a problem that is still true as new. An open problem of a switched-off kind that clears is closed without a message. Switching a kind off also silences "that check could not run" for that kind; "the whole scan failed" is always sent. A name that is not a kind is refused ("not an alert kind: ...").

- Who: an admin.
- When a part is off: the kinds of check that belong to that part are neither run nor listed.

### Each alert says what is wrong, what to do and the detail

Each problem in a message carries its diagnosis, then "What to do: <fix>", then "Detail: <technical line>". A message to another service about one problem has the subject "CC Sync: <title> - <subject>" and ends "Open the CC Sync dashboard for the full picture." A message body is cut at 60,000 characters. Wherever a text says "send us ...", the site's support contact is added when the site has one, in alerts, combined messages, the weekly report and the server check alike. Each problem reaches the admin in one wording: a problem the server both shows among its open problems and checks for on its own goes out once, not twice.

### Everything one check finds goes out by e-mail as one message

By e-mail, everything one check finds goes out as one combined message; another service gets one message per problem. The combined message's subject is, in this order of priority:

- the catch-up: "CC Sync: here is everything currently open (N)";
- new problems: "CC Sync: 1 new problem: <title>" or "CC Sync: N new problem(s)";
- only repeats: "CC Sync: still not fixed after D day(s): <first two headlines> and K more";
- only clearances: "CC Sync: cleared - <headline>" or "CC Sync: N problem(s) cleared".

The body lists serious problems before warnings. New problems appear in full under "PROBLEM:" (an error) or "TO LOOK AT:" (a warning). Repeats are one line each under "STILL NOT FIXED" with "(open for D day(s))", then "The full description of each of these went out when it was first found. Nothing about them has changed." Clearances appear under "CLEARED:". Then "Still open from before: N (see the dashboard)" when warnings or say-once problems are still open. Days open count from the first alert after the problem last cleared, and are at least 1.

### A serious problem is repeated once a day while it lasts

In messages, a problem of error severity counts as a serious problem and a warning as something to look at. A serious problem is sent when first found and then once a day for as long as it stays true. A warning is sent once and not again until it has cleared and come back. Some kinds are said once only while they stay true, and say so on their own description. A time that cannot be read counts as never sent.

### People are told when a problem clears

An open problem that a check which ran fully no longer finds is declared cleared, with the subject "CC Sync: cleared - <title> - <subject>" and the body "This has cleared on its own or somebody fixed it. No action is needed." Whether a problem is open survives a server restart. When a computer stops reporting what a check looks at, an open problem about it is closed without any message ("closed without a message: that computer no longer reports what this checks").

### Everything already open is sent once a destination is first set

Problems found while no destination was set are not lost. When an admin first sets a destination, every problem still open is sent at the next check, in a message that opens "CC Sync: here is everything currently open (N)" and says it is the catch-up, not N new faults.

### A message that cannot be sent is tried again and never holds up the checks

No failure to send ever stops or slows the server's checking. A message that cannot go out in time waits and goes later, whole: a combined message is sent whole or not at all. While messages are waiting a warning stands among the open problems: "Sending this server's alerts took longer than a check is allowed, so N of them were left for the next check. ..." with the fix to press "Send a test" in the alert settings and time it. It clears on the first check that sends everything.

Every message whose send fails (an alert, a clearance, the weekly report, the daily "still here", the daily footage-not-at-home mail, the server check's report) is tried again after about 10 minutes, then an hour, then 6 hours, and keeps being tried until it goes; it is shown as not delivered until it does, and is never dropped.

### A failure to deliver is named in plain words

Each failure is shown in the list of what was sent with its reason:

- for another service: "no webhook URL is set", "the webhook URL must be https", "the webhook answered HTTP N", "could not reach the webhook (...)";
- for e-mail: "no mail server is set", "e-mail needs a sender address and at least one recipient", the certificate message, "the mail server refused the sign-in", "could not send through <host> (...)". The mail server's own reply to a refused sign-in is never repeated, because it can carry the password.

With no destination, each message is recorded as not delivered because none is set.

### An admin sees every message that was sent

The list of what was sent shows the most recent 200 messages, newest first, grouped by the message each problem went out in ("<ago>: one message, N findings"), with whether all of them were delivered. Each shows when, what kind (an alert, a clearance, the daily "still here", the weekly report, a test, the server check, the daily footage-not-at-home mail), the subject, where it went, and "sent" or why it failed. A failed send is kept. Empty, it reads "Nothing has been sent yet." Entries are forgotten after 120 days.

- Who: an admin.
- Name and search words: Alerts sent. Search words: sent alerts, mail history, messages, delivered.

### A weekly report on the whole studio goes out every Monday at 08:00

The weekly report is on unless an admin switches it off. It goes out on Monday at 08:00 in the site's time zone, staying at 08:00 across daylight-saving changes. If the server was down all Monday it is sent when it comes back, and a restart never sends it twice. With no destination it is still put together and recorded as made but not sent, which is not a failure. When the most recent weekly report could not be sent, a serious problem "the weekly report could not be sent" stands until any later real delivery (a test, an alert, a clearance) succeeds.

The subject is "CC Sync weekly: N computer(s), E problem(s), W thing(s) to look at". The body, in order:

1. "Fleet health for the week ending <now>." and "N computer(s) reporting."
2. "PROBLEMS (n)" and "THINGS TO LOOK AT (n)", with every open problem's diagnosis, fix and detail, or "none."
3. "BUILDS": how many computers run each version ("<version>: 6 of 8 computers"), then each out-of-date or unknown computer ("<who> has been on <build> for <span>; current for <platform> is <version>").
4. "WHAT CHANGED THIS WEEK (n entries)": up to 40 lines from the history of changes, then "... and N more in the history of changes." or "nothing."
5. "ALERTS SENT THIS WEEK": up to 50, with failures marked "(SEND FAILED: ...)".
6. "SHARED WORK: q queued, r running, a abandoned this week".
7. "WHAT IS PROTECTED (X of 9 confirmed, Y missing, Z unverifiable)", then each line as its state and title, its detail and the projects or computers concerned, and for any line not confirmed "WHAT TO DO:" and its repair. It reports the last protection check and never checks on the spot. When no check has ever run: "(no protection pass has run on this server yet)". When it cannot be read: "WHAT IS PROTECTED: this section could not be read this week. Treat it as unchecked, not as fine."
8. "RECOVERABLE DELETED FILES", with each computer's size and count of deleted files that can still be recovered.
9. "CHECKED AND FOUND NOTHING WRONG (k of N)" with "ok - <what>" for each clean check, then "COULD NOT BE CHECKED (n)".
10. "NOT SENT AS ALERTS (n, switched off in the alert settings; still checked and listed above)" with "off - <what>" for each switched-off kind.
11. The closing line "This report is composed from what the dashboard already knows. Anything it could not read is named above rather than left out."


### An admin can ask for a daily "still here" message so that silence means the server is down

The daily "still here" message is off unless an admin switches it on, and is only sent when a destination is set. It goes once per calendar day in the site's time zone. Its subject is "CC Sync: all quiet - N computer(s), E problem(s)" when nothing serious is open, otherwise "CC Sync: still here - ...". The body explains "IF THESE STOP ARRIVING, THE SERVER ITSELF IS DOWN", lists how many computers are known, the problems open and the things to look at, and says how to turn the message off in the alert settings. It is never itself a problem, never "cleared" and never among the open problems.


### The assistant checks the server at set hours and mails what needs a person

An admin can switch on a server check: "Assistant reads everything this server knows is open, stuck or failing and mails you what needs a person, at these hours in the site's time zone. It only reads; a reply to its email can carry out the actions it offers." The report goes to the alert recipients, with numbered suggested actions that a reply can carry out.

It is off unless an admin switches it on. It runs at up to four hours a day, 06:00 and 18:00 unless set otherwise; the hours are 0 to 23, typed comma-separated (for example "6,18"), with repeats removed and sorted, "at most 4 checks a day", and a blank field saves the usual hours, never "never". If the server was down at one of those hours, the check runs when the server comes back, and a restart never runs it twice. It never runs while switched off or with no alert destination. Only one runs at a time: a second is refused with "a server check is already running" or "a server check has been running since <time>"; one that has been running for more than 90 minutes is taken as dead and blocks nothing. It never holds up the server's other work.

- Who: an admin.
- When the assistant is off: the server check is neither run nor shown anywhere, and every other alert works as described.

### An admin runs the server check now

"Run now" starts a check whatever the schedule: "Server check started. The report arrives by mail in a few minutes." (recorded in the history of changes), or "the server check did not start: <why>". It is refused with "the server check is off. Turn it on and save first." or "no alert channel is set up, so the report would go nowhere." It also starts looking for replies at once.

- Who: an admin.

### The server check says when the assistant cannot do its part

The check needs the assistant to be switched on for the site and connected. When it is not, the admin is told why in plain words (switched off on this server, not set up on this server, or no key entered), each pointing to the assistant's settings, with "It cannot run its analysis: <why>. Each check will mail a plain summary instead." and the check sends its plain report instead.


### In the server check the assistant only reads and never sees a secret

The assistant may read and search but never change, run or fetch anything. It is shown what the dashboard knows: the open problems, the alerts of the last 48 hours, the counts of open problems, the state of every fact the server re-checks, the state of the server's own background work, every computer's state, live transfers and the queue, open shared work with counts by kind and state, the published builds, and the actions offered by the previous check and what became of them. It may also read how the product itself works when it needs to. A part that cannot be read is marked as such. Nothing from the site's settings or stored secrets is given to it: any field named like a password, token, secret or key, and any value that looks like a key, is blanked first. It has 20 minutes to answer.


### The server check lists only what needs a person, most important first

The assistant lists what needs a person, most important first, each with its evidence and a suggested action. It does not list what is fine. A computer with no projects ticked is never a problem. When nothing needs a person it says all clear, and only then. A fault in the product's own workings is a finding with a ready-to-paste instruction for fixing it, never an action. At most 30 findings and 20 actions are kept; each finding is serious, a warning or for information (a warning when unclear); each text is cut at 4,000 characters, and a long dash is written as " - ".

An action is offered only when it is one of the actions a reply can carry out, with exactly its details, has a number from 1 to 99 not used twice, and passes that action's own check against the present state of the studio. Duplicates are dropped. Proposals that fail are listed under "Suggested but not offered:" with the reason.


### The server check's mail is a short list of what needs the admin and what a reply can do

The subject is "[CC Sync] Server check: <Assistant's subject, or 'all clear' / 'what needs you'>". The body has the headline, or "All clear: nothing on the server or the fleet needs a person."; then "WHAT NEEDS YOU" with numbered findings "[SEVERITY] title", "Evidence:", "Suggested:", "Actions: [n]" and, where there is one, the ready-to-paste instruction for fixing the product; then "ACTIONS A REPLY CAN CARRY OUT" with "[n] <action> - <why>"; then the actions not offered. It ends with one of:

- 'To carry any of these out, reply to this email, e.g. "do 1 and 3".' and "Reference: CCT-<code>   (valid until <local time>, each action runs once)";
- with replies off: "Replies are switched off on this server (the server check's reply address in the alert settings), so these can only be done on the dashboard.";
- "Nothing in this check can be done by reply."

The reference is random and valid for 48 hours. The server keeps only a fingerprint of it, so it can check a reference but never read one back, and its own copy of the mail shows only the reference's last four characters. Replies are directed to the reply address only when actions were offered and replies are on. The mail is recorded in the list of what was sent.


### The server check always reports, even when the assistant could not

When the analysis cannot run (the assistant is not available, did not answer within 20 minutes, could not start, failed, or gave no usable answer), a plain report is sent instead. Its subject is "[CC Sync] Server check: the analysis could not run"; the body names the reason, then what the dashboard itself can say: the open problems (up to 40, by kind and subject), "Computers not syncing:" with each one's reason, and "Background jobs failing:", then "This message is sent because the check always reports. If these stop arriving, the server check itself is broken."

If the check itself fails, the subject is "[CC Sync] Server check: the check failed" and the body "The server check failed before it could finish: <error> ... Nothing was changed. The next check will try again."


### An admin sees the server check's state and its past reports

The server check shows: "Server check is on." or "Server check is off."; whether the assistant is available to it and, if not, why; the incoming mail server used for replies; whether replies are read ("Replies are not being read (they need a reply address and mail as the channel)."); the time zone; "A check has been running since <time>." while one runs; the last check as "last check <time>, <ok, plain report or failed>[, the email did not go out]." with "read its report", which shows the report as mailed (with the reference masked), or "No check has run yet."; and "replies last read <ago>: <detail>".

Each check is kept with the actions it offered, each action's number, what it does, why, whether it was done and its result, and the reply that acted on it and when; each reply handled is kept with when it arrived, who sent it, which check it answered, the verdict and a detail. Offered actions whose reference has run out are marked expired. Checks, their actions and their replies are deleted after 60 days.

- Who: an admin.

### Replies to the server check can carry out its actions

Replies are read only when the check is on, a reply address is set and alerts go by e-mail. The reply address is one plain e-mail address, "The only mail the server ever reads"; blank turns replies off, and the report is still sent. The server reads replies with the same mail account it sends from. The incoming mail server can be typed, or left blank to be worked out from the outgoing one's name in the usual way providers name them (for Gmail it is known); when it cannot be worked out, the admin is told "replies cannot be read: the incoming mail server, the mail user or the mail password is not set". A reply is picked up within about two minutes; replies from the last two days are considered, read or unread. The certificate check follows the alert e-mail setting. A failure to read is shown as "could not read the inbox (<kind>: <server message>)".

- Who: an admin sets it up. Any alert recipient replies.

### Only a genuine reply from an alert recipient with a current reference is acted on

Each reply is handled once. A message not actually addressed to the reply address is skipped and left as it was. A reply is refused when:

- its sender is not one of the alert recipients;
- the receiving mail provider did not vouch that it really came from the sender's domain (for Gmail, only Google's own verdict counts), unless the sender is the mail account itself and the identical message is in that account's sent mail, with no explicit failed verdict;
- it carries no reference from a check ("the reply carries no reference (CCT-...) from a check this server sent"), or one older than 48 hours ("the reference in the reply has expired (a check's actions can be chosen for 48 hours)").

An accepted reply is recorded before anything is done, so a crash never acts on it twice. Handled replies are marked read.

A refused reply is never answered by mail. Instead a warning stands among the open problems, named by the test that failed: "A reply to the server check email from <who> was not acted on: <reason>. Nothing was changed, and no answer was sent, because answering a forged sender sends mail to whoever it pretended to be." The fixes: reply from an address among the alert recipients; when the mail provider did not vouch for the message, use the dashboard's own buttons; reply to the most recent check mail within 48 hours. It closes itself when a later reply from the same sender is acted on, or after 7 days.


### A reply says all, none or which numbers, or asks in its own words

Only the reply's own words count; the quoted original and the signature are ignored, and at most 4,000 characters are read. "all", "do all" or "all of them" means every offered action; "none" or "nothing" means none; a list of numbers such as "1, 3", "do 1 and 3" or "1 & 2" means those. Anything else is read by the assistant, which gives up after 3 minutes, to find which numbers to do or skip and what is unclear. When the assistant is not available: "the reply is not a list of numbers, and Assistant is not available to read it (...)". Each chosen action runs once, in order, and each action can run only once across all replies. Each outcome is done, refused (its check said no now), failed, "not done again", or "not understood" (it was not offered).

An accepted reply gets a confirmation with the subject "Re: <original subject>": "What your reply asked for:" then "[n] <action>: done / refused / failed / not done again / not understood - <detail>", or "Your reply did not choose any of the offered actions, so nothing was changed."; then "Not clear from your reply: ...", "Note: ...", "Nothing else was changed.", how to carry out another, and the reference line again. It is recorded in the list of what was sent.


### What a reply to the server check can carry out

Each action does exactly what the matching control on the dashboard does, is checked when offered and again when chosen (a failed check is a refusal with its reason), and is recorded in the history of changes as done by the server check on behalf of the sender. Details are limited to 128 characters without control characters, and editors' names are taken in lower case.

| Action | Refused when |
|---|---|
| Push the current version for that computer's operating system to a computer ("asked <who> to update to X on its next report"), exactly as the dashboard's push does (see Releases and updates: Pushing updates and seeing who has what, "An admin pushes a version to one computer"); a computer already running it is not refused | no such computer, no current version of the app is published for that computer's operating system, or that computer kept crashing on that version and went back from it |
| Withdraw a pushed update for a computer (it succeeds even when nothing was waiting) | no such computer |
| Resume downloads on a computer | no such computer, or its last report does not show its downloads stopped themselves |
| Start syncing again everywhere (end the studio-wide stop) | no studio-wide stop in force |
| Keep syncing stopped everywhere, for 24 hours from the reply, keeping its reason and start | no studio-wide stop in force |
| Cancel a piece of shared work by number (it stops the next time its computer reports, or when the server next looks at it) | no such work, or already finished |
| Dismiss an open problem by number ("it comes back by itself if the condition is still true") | no open problem with that number |
| Ask a computer for its diagnostics | never refused |
| Ask the server's background work to run now | the server's background work is not running |

Letting a computer waiting to join the studio in is deliberately not possible by reply.


#### Lessons

- Met: DSH-097, DSH-098, DSH-099, DSH-100, DSH-101, DSH-102.

## Settings and setup

### Every setting of the site

Each setting below is one thing an admin can change for the whole site. Each has a plain name, what it does for people, its default, and words to find it by. A switch whose value cannot be read counts as off.

These are the core's site settings. Each part's own site settings are given, with their names and search words, in that part's own description; among them the YouTube downloads switch (see YouTube downloads: Keeping the downloader working, "A site switches YouTube downloads on and off while the server runs") and YouTube's extra measures against being blocked (see YouTube downloads: Signing in to YouTube, "A site decides whether signed-in YouTube sessions may be used on editors' computers"). A few core settings are described in full with the behaviour they belong to, and are only pointed to here: the studio's time zone, which the weekly report, the daily "still here" message and the server check keep to (see The server: installing it and keeping it running: NAS speed, load and clock, "Schedules run on the studio's own clock"); the shared libraries every editor's computer gets (see The server: installing it and keeping it running: Settings and secrets, "The kind of NAS, the project layout and the shared libraries"); and updating editors' computers by themselves (see Releases and updates: Offering an update to a computer, "A studio can let its computers take newer versions without anyone clicking").

- Setting: Studio name. Does: names the studio in the dashboard's title and wherever the product shows its brand. Default: blank. Who: an admin. Applies to: the site. Search words: studio name, brand, company, title, organisation.
- Setting: Studio short name. Does: a short form of the studio's name for tight spots, such as the hover text of the app's icon on editors' computers. Default: blank. Who: an admin. Applies to: the site. Search words: short name, abbreviation, brand, tray, tooltip.
- Setting: Product name. Does: the name the product goes by on every page, in every message, in the installed app and on editors' computers. Default: CC Sync. Who: an admin. Applies to: the site. Search words: product name, brand, app name, rename.
- Setting: Mark on editors' computers. Does: the picture editors see as the product's icon on their computers: the product's own mark, another mark shipped with the app, or a picture on the editor's computer. Default: the product's own mark. Who: an admin. Applies to: the site. Search words: logo, icon, mark, brand, picture.
- Setting: Support contact. Does: where the studio's people are sent for help; added as "Support: <address>" wherever the product tells someone to send something to support. Default: blank, which uses the vendor's support address. Who: an admin. Applies to: the site. Search words: support, help contact, email, who to ask.
- Setting: Where editors see the studio's tree. Does: the drive letter (or, on a Mac-style tree, the absolute folder) at which every editor's computer finds the studio's shared tree. Default: P:\. Who: an admin, and only before any computer has joined. Applies to: the site. Search words: drive letter, P drive, tree, mount, path.
- Setting: Tree name. Does: the name of the studio's shared tree as editors see it. Default: the name given when the server was set up. Who: an admin, and only before any computer has joined. Applies to: the site. Search words: tree name, share, root folder, library name.
- Setting: Where the tree lives on the server. Does: the folder on the NAS that holds the studio's tree. Default: the folder given when the server was set up. Who: an admin, and only before any computer has joined. Applies to: the site. Search words: server folder, NAS path, share, storage, tree location.
- Setting: Folders in every new project. Does: the list of folders laid down in each new project. Default: the product's standard project folders. Who: an admin. Applies to: the site. Search words: project template, folders, new project, structure, layout.
- Setting: Dashboard address. Does: the address editors' computers and browsers use to reach the dashboard, and that every "open the dashboard" link follows. Default: learned by the server itself where it can. Who: an admin. Applies to: the site. Search words: dashboard address, URL, link, web address, domain.
- Setting: Which assistant to use. Does: pins one of the connected assistants for every feature that uses one; left unpinned, each feature uses the first available in the owner's order of preference. Default: unpinned. Who: an admin. Applies to: the site. Search words: assistant, AI, provider, model, pin.
- Setting: Who is told about problems. Does: where the server sends what it finds: nobody, by e-mail, or posted to another service's web address. Default: nobody. Who: an admin. Applies to: the site. Search words: alerts, notify, destination, channel, who is told.
- Setting: Alert recipients. Does: the e-mail addresses that receive alerts, reports, the daily footage-not-at-home mail and the server check, separated by commas or semicolons. Default: blank. Who: an admin. Applies to: the site. Search words: recipients, alert email, to address, who gets mail.
- Setting: Sender address. Does: the address alert mail comes from. Default: blank. Who: an admin. Applies to: the site. Search words: sender, from address, mail from, alert email.
- Setting: Outgoing mail server. Does: the mail server alerts are sent through. Default: blank. Who: an admin. Applies to: the site. Search words: mail server, outgoing mail, email server, send mail.
- Setting: Mail server port. Does: the port of the outgoing mail server. Default: 587. Who: an admin. Applies to: the site. Search words: port, 587, 465, mail port.
- Setting: Mail sign-in name. Does: the account name used to sign in to the mail server. Default: blank. Who: an admin. Applies to: the site. Search words: mail user, username, mail login, account.
- Setting: Mail password. Does: the password of the mail account, kept apart and never shown back. Default: not set. Who: an admin. Applies to: the site. Search words: mail password, app password, email password, sign in.
- Setting: Secure mail connection. Does: encrypts the connection to the mail server; it cannot be turned off while a mail sign-in is set, so a password never crosses unencrypted. Default: on. Who: an admin. Applies to: the site. Search words: encryption, secure, TLS, mail security.
- Setting: Verify the mail server's certificate. Does: refuses to send when the mail server's certificate does not match it; off only for a studio's own internal mail server with its own certificate. Default: on. Who: an admin. Applies to: the site. Search words: certificate, verify, mail security, self-signed.
- Setting: Alert web address. Does: the https address of another service that each alert is posted to. Default: blank. Who: an admin. Applies to: the site. Search words: webhook, web address, post alerts, chat, integration.
- Setting: Kinds of problem that send a message. Does: one tick per kind of check; an unticked kind is still checked and shown but sends no message. Default: every kind ticked. Who: an admin. Applies to: the site. Search words: alert kinds, mute, silence, which alerts, notifications.
- Setting: Weekly report. Does: sends the weekly report on the whole studio every Monday at 08:00. Default: on. Who: an admin. Applies to: the site. Search words: weekly report, summary, Monday, digest.
- Setting: Daily "still here" message. Does: sends one short message a day, so that silence means the server is down. Default: off. Who: an admin. Applies to: the site. Search words: heartbeat, still here, daily, all quiet, server down.
- Setting: Server check. Does: lets the assistant check the server at set hours and mail what needs a person. Default: off. Who: an admin. Applies to: the site. Search words: server check, assistant report, triage, daily check.
- Setting: Server check hours. Does: the hours of the day (up to four) at which the server check runs. Default: 06:00 and 18:00. Who: an admin. Applies to: the site. Search words: check hours, schedule, when, times.
- Setting: Reply address for the server check. Does: the one address whose incoming mail the server reads, so that a reply can carry out the check's actions; blank means replies are not read. Default: blank. Who: an admin. Applies to: the site. Search words: reply address, reply by email, actions, inbox.
- Setting: Incoming mail server for replies. Does: where the server reads replies to the server check from. Default: blank, worked out from the outgoing mail server. Who: an admin. Applies to: the site. Search words: incoming mail, inbox server, replies, read mail.
- Name and search words: Settings. Search words: settings, preferences, configure, options, setup.

### Saving settings checks every field first and one bad field changes nothing

Only an admin may read or change the site's settings ("log in first", "admins only"). A save sends the whole form. Each save says "saving...", then "saved at HH:MM:SS" by the person's own clock, or "could not save: <reason>"; a refusal that names a setting opens the place holding it and keeps what the admin typed. A save that would switch a kind of reporting from computers off first asks the admin, with "Stop reporting", and nothing is saved until they confirm (see Accounts, privacy and the legal paperwork: What the product records about a person, "An admin switches a kind of reporting off for the whole studio").

Every value is trimmed. Text holding control characters is refused ("must not contain control characters"), as is any alert value over 400 characters. Whole numbers may be blank but not negative ("must not be negative", "'x' is not a whole number"). Yes-or-no settings take on, off or blank (blank is off). A setting the product does not know is refused ("not a recognised site setting"). The whole form is checked before anything is written, so one bad field changes nothing, and the reason is shown. Each setting records when and by whom it was last changed, and can be cleared back to its default.

A saved setting takes effect everywhere, on the server and on every computer, within seconds and with no restart. Settings are held in one place, the dashboard; nothing typed elsewhere overrides them. No core behaviour depends on whether an optional part is switched on.

- Who: an admin.

### A value the server learns for itself is shown beside the setting

Where the server can learn a value for itself (the dashboard's own address among them), the value it learned is shown. A setting is locked only while a live source supplies its value right now; when the server cannot be sure, the setting stays editable, and a value that differs elsewhere is shown beside it. Wherever a computer's own setting is shown on the dashboard and cannot be changed there, the page says in words where to change it on that computer.

### Where the tree sits is fixed once any computer has joined

Where editors see the studio's tree, the tree's name and where the tree lives on the server are fixed, and shown read-only, once any computer has joined, because every computer finds its footage there; there is no way to change them after that. The shape the drive letter must have, the lock and what a refused change says are described in full elsewhere (see The server: installing it and keeping it running: Settings and secrets, "The tree, the drive letter and the dashboard's address are set once and then locked").

### Project folders and shared libraries stay inside the studio's tree

Each folder in the list made in every new project, and each shared library, must be a folder under the tree; the checks and what the admin is told are described with those settings (see The server: installing it and keeping it running: Settings and secrets, "The kind of NAS, the project layout and the shared libraries").

### The support contact is added wherever the product says to ask for help

Help text that tells someone to send something to "us" or to "support" has "Support: <address>" added, never twice, in pages, alerts and reports alike. With no studio contact set, the vendor's support address is used. The settings and the settings export show only the studio's own value, never the vendor's.

### Every change to the settings is recorded and the last one can be undone

Every save, import, undo and setup-checklist save that changes a setting is recorded with when, who made it, how (save, import or undo) and which settings it touched; a saved alert destination is recorded by its kind only, never its address, and no password or other secret is ever recorded. The history lists the most recent changes, each as "<what was done> by <person>", how long ago (the exact time on hover) and how many settings, with the total recorded ("No site setting changes recorded yet." when there are none).

"Undo the last change" asks "Put back the <n> setting(s) changed by <person> <ago> (<exact time>)?" and puts back exactly the earlier values that change replaced, through every check a save goes through. It undoes exactly that change, never a newer one made meanwhile: if someone saved since, it is refused with "the newest change is no longer the one you confirmed (someone saved since): reload the page". With nothing recorded it is refused ("no site setting change is recorded to undo"). It is disabled until the history has loaded. An undo that would switch a kind of reporting from computers off first asks the same question as a save, with "Stop reporting" (see Accounts, privacy and the legal paperwork: What the product records about a person, "An admin switches a kind of reporting off for the whole studio"). The undo is itself recorded, so it can be undone.

- Who: an admin.

### An admin exports the settings as text and imports them by pasting

An admin can export the site's settings as a plain-text settings file, and import one by pasting it, up to 65,536 characters. Pasting nothing is refused ("could not import", asking for the settings file first). Before anything is written the product works out the differences: "Nothing in that text differs from the current settings. Nothing was changed." or "This will change <n> setting(s), including <setting> from <old or (blank)> to <new or (blank)>, ... [, and <k> more]. Apply it?" (the first three named). An import that would switch a kind of reporting from computers off also asks the same question as a save, with "Stop reporting" (see Accounts, privacy and the legal paperwork: What the product records about a person, "An admin switches a kind of reporting off for the whole studio"). Applying goes through every check a save does, reloads the page, keeps the replaced values, and appears in the history so it can be undone like a save; a failure says "could not import: <reason>". Lines the dashboard does not hold are ignored; text with nothing it recognises is refused; text that cannot be read is refused with the reason. The studio's projects folder is always named "Projects", and an import naming it otherwise is refused.

- Who: an admin.

### The setup checklist names a real next step for every item

A new site is taken through a setup checklist. Every item is a real check of the site as it stands, shown as to do, a warning or done, and names its next action in words. No item shows placeholder text, and no step a site needs depends on a check that cannot be answered. The alert step is described under "Setup asks who should be told when something goes wrong".

- Who: an admin.
- Name and search words: Setup checklist. Search words: setup, getting started, checklist, first steps, wizard.

### An admin connects the assistant with a short guided setup

The assistant's settings list only the ways of reaching an assistant that are connected, plus "add new". Adding one is a picker, then a short guided setup ending in a test. The usual way is a paid key, typed once and never shown back.

The other way is running the assistant on a subscription. It is off on every new site, and the guided setup is the one place it is switched on or off: switching it on means accepting the notice inside that setup, then a download that is installed only when it is verified as the publisher's own, a sign-in in the browser with a code to paste back, and the test; switching it off is done from the same setup. No other switch, tick box or setting turns it on. A way to point at a copy the admin installed and vouches for themselves stays offered inside the same setup.

The setup survives the page being refreshed, and a successful sign-in is seen at once by its test and by every feature that uses it.

- Who: an admin.
- When the assistant is off: none of this is shown.

### Each feature uses the first assistant available unless an admin pins one

Every feature that uses the assistant takes the first one available in the owner's order of preference, unless an admin has pinned one. A pinned one that is not available is refused, never quietly replaced. The page shows which one is in use.

- Who: an admin pins.
- When the assistant is off: none of this is shown.

### A setup button that fails says what failed and what to do instead

Any button an admin presses to set something up answers, when it fails, with what failed, that nothing was left half installed, and the other way to get it done. A check that cannot finish is a refusal, never a yes.

### An admin sees whether the server and every app are up to date

An admin sees the server's version and the app's version against the newest offered, and how many computers run each version. An offer that has not been checked reads "not checked", never "up to date".

- Who: an admin.

#### Lessons

- Met: DSH-103, DSH-104, DSH-105, DSH-106, DSH-107, DSH-108, DSH-109, DSH-110, DSH-111, DSH-112, DSH-113.

## Pages that refresh and answer clicks

### Every page says how fresh it is and says plainly when it has stopped updating

Every signed-in page shows "updated <time ago>": when the server last answered it successfully, by the server's own clock, re-read every 30 seconds while the page is in view. It never claims to be fresh while it cannot reach the server.

When the server cannot read how syncing of project folders stands, every page adds the warning "the data on this page may be stale" with a "What to do" link to the help on putting it right. On a phone only the warning is shown, never the time. When the server cannot tell, no warning is shown.

When a page's own refreshes start failing, a warning held at the bottom of the page reads "THIS PAGE HAS STOPPED UPDATING (last update <N seconds / minutes / hours ago>). Nothing below is current." followed by the reason:

- the session ended: "Your session has ended. Reload the page and sign in again.";
- refused to this account: "The server refused this to your account (403)[: <server's reason>]. Reload the page; if you were signed out, sign in again.";
- any other error: "The server answered <status>. Reload the page to try again.";
- the server could not be reached: "The server could not be reached. Reload the page to try again.";
- no answer in time: "The server did not answer in time. Reload the page to try again."

The warning never covers anything on the page, and it goes by itself the moment any exchange with the server succeeds. Text from the server is always shown as plain text.

Only the page's own refreshes failing bring this warning. A change a person asked for with a button, form or switch that the server refuses never marks the page as out of date: it gets a short note directly above the control that was used (see The whole product: Could not check, refusals and nothing silent, "A refused change is shown beside the control that asked for it").

- Phone and desk: on a phone only the stale warning shows, never the "updated" time.

### Pages keep themselves current and catch up the moment they are shown again

The parts of a page refresh themselves without anyone pressing anything. On a touch device (a phone or tablet) the liveliest parts refresh less often: what is moving now (on the Overview and on the Transfers page), which a desk refreshes every 2 seconds, refreshes every 10 seconds, and the list of which computers hold a project's media, which a desk refreshes every 5 seconds, refreshes every 15 seconds; slower parts (between every 10 seconds and every minute) are the same everywhere. While the tab or the installed app is hidden, nothing is fetched at all; the moment it is shown again every part refreshes once, at once, so what a person sees on returning is current rather than minutes old.

- Phone and desk: touch devices refresh their liveliest parts every 10 or 15 seconds instead of every 2 or 5.

### The studio's picture on the dashboard stays fresh on its own

Without anyone pressing anything, what the dashboard shows about the studio is kept current:

| What is shown | At most this old |
|---|---|
| Which computers are connected, and from where | about 15 seconds |
| How far each computer is through each project, and which files it still lacks | about a minute |
| The projects and computers the NAS knows of | about two minutes |
| A folder newly marked as a project on the NAS | set up within about five minutes |
| A file that reached the server showing as on the server | within five minutes (a newly found project is counted first, within a minute or two; see The dashboard: Projects, "The server counts what each project holds on the NAS") |
| What is protected | about 15 minutes |
| The server's own checks for problems | about 10 minutes |

When the server starts, all of this is gathered straight away, not after the first wait.

### A refresh never takes away what a person is in the middle of

A part of a page is not refreshed while the person is using it: while their typing cursor is in one of its text boxes or drop-down lists, while it holds a field they changed and have not sent (up to 5 minutes after the last change), while a change they sent is still waiting for its answer (up to 5 minutes), while a folder browser opened from it is open (up to 5 minutes), or while a pop-over of it is open. That refresh is skipped and the next one runs as normal; the same holds for the refresh on returning to the tab. While a question asking the person to confirm something is open, nothing on the page refreshes.

When a part does refresh, every section the person folded open or closed stays as they left it, fold-out rows they opened in a list stay open and closed ones stay closed, and an open sheet inside the refreshed part reopens at the same scroll position. A refresh never throws away typed input, an open list, picker, sheet or switch, an answer that has not arrived yet, or a secret shown once. Every secret shown once has a copy button.

### The answer to a click appears beside the control that was pressed

Every control that can take longer than a second shows that it is working and cannot be pressed again until its answer arrives. The answer appears in view beside the control that was pressed, or on the page if that control has gone, replacing any earlier answer there, even while other parts of the page refresh.

A person can fold sections of a page away, and the choice is kept. A folded section opens by itself, without changing the remembered choice, when: an answer to something the person did lands in it, a link points inside it, an error, result or refusal lands in it, a secret shown once appears in it, or a settings save refuses a field in it. An answer that appears in a separate place is scrolled into view and given keyboard focus, unless it came from a timed refresh.

### Returning to a page puts the person back where they were

Returning to a page puts the person back where they were on it, and a link that names a place on a page leads there instead (see The dashboard: Overview, menus and finding things, "Every page remembers where the person was on it" and "A link can lead to any place on a page").

### A page drawn before an update reloads instead of acting

After the dashboard is updated, the first click on a page drawn before the update reloads the page instead of acting, so nothing is ever written from an out-of-date page and a stale tab can never overwrite newer work.

### When a session ends the person is taken to sign in and back

When a person's session expires, the next refresh or click takes them to sign in, and then back to the page they were on. A run of clicks stops at the first one that fails. A request that is not for a page (a program asking for data) gets a plain answer that it is signed out, never the sign-in page.

### A part that cannot be read spoils only itself

When one source of a page is busy or fails, only its own part is affected: it says "could not read this right now" with its last known state and when that was, and the rest of the page draws as normal. An empty answer is never stated for something that could not be read. A badly formed stored value spoils at most its own cell, and a stored time with no time zone is read as universal time.

### Admins are told when a page failed for someone

When a page fails with an error, a serious problem stands for admins, one per page and kind of error, counted: "N time(s) a request to <page> failed with an error (<kind>). Whoever was using that page saw a failure. What went wrong: <message> Where: <where in the product>". The message has secrets removed and is cut at 700 characters, and the whole text at 1,500. The fix is to copy the text to support. The page is named in its general form; where that is not known only its first two parts are kept, so the secret part of a link handed to a client is never stored. The problem closes itself after 24 hours without happening again.

### Every control on a warning band can be read

Every button and link on a warning band, or any coloured band, stands out clearly against that band's own colour.

#### Lessons

- Met: DSH-114, DSH-115, DSH-116, DSH-117, DSH-118, DSH-119, DSH-120, DSH-121, DSH-122, DSH-123, DSH-124, DSH-125.

## Speed under load

### Pages answer within a second however large the studio grows

The home page loads within a second for a studio of 20 computers, and stays fast at 50 editors and 400 projects. A refresh that finds nothing changed costs next to nothing.

### One slow action never holds up anyone else

While one change is being written, every other page is still answered within a second, and every computer's report finishes in about a tenth of a second. When the server truly cannot take something at that moment it says it is busy at once rather than making the person wait. No admin action, upload, search or other long piece of work delays other people's pages by more than a second, or the computers' reports beyond that tenth of a second: long work runs alongside and shows its progress.

### Admins are told when the server was too busy to answer

The dashboard raises a problem for admins, counted, when:

- recording the computers' check-ins held up the server for more than 5 seconds at a stretch (shown on the home page);
- a page waited too long for the server and was refused;
- one change held up other work for longer than a page waits ("Nothing on the reporting computer causes this and nothing needs unticking...");
- one of the server's own checks took over 60 seconds; it closes when that check next finishes in time.

The first three close themselves after 24 hours without happening again.

- Who: admins see these.

#### Lessons

- Met: DSH-126, DSH-127, DSH-128.

## Phones and the installed app

### The dashboard installs as an app on a phone or a desk

The dashboard offers itself as an app that can be installed, carrying the site's product name and the description "The fleet dashboard: who is syncing, what is transferring, what is wrong." Installed, it opens on the overview in its own window with no browser bars (or minimal ones where the device insists), in any orientation, with proper icons for phones, including ones a phone may crop to a circle or a rounded square. Where the browser offers installation, an "install this app" button is shown; pressing it opens the browser's own install dialog once and the button goes away. Nothing is shown when the dashboard is already running as an installed app, or when the browser makes no such offer (Safari, Firefox). Installation and the offline page need the dashboard to be reached over https (or on the same computer); over plain http on the studio's network nothing is offered and nothing is said.

- Who: anyone signed in.
- Phone and desk: browsers that do not offer installation show no button.

### When the dashboard cannot be reached the installed app says so

Opening a dashboard page always asks the server first. Only when the server cannot be reached at all is an offline page shown, with the studio's name and "This device cannot reach the dashboard right now. Nothing here is live: check the network, then try again." and "Try again", which reloads the address that failed (from the offline page itself it goes to the overview). If even the offline page is missing, a bare "offline" is shown instead of a browser error. The offline page carries nobody's name, no role and nothing a form needs to act. The device keeps only the dashboard's general files (the look, its scripts, icons and the offline page), so they appear at once and the offline page draws properly. Nothing that depends on who is asking (any data, any panel, the sign-in page, or the pages of the parts) is ever kept on the device or shown from a stored copy; it always comes from the server.

### A new version reaches every installed app within two visits

Every new version of the dashboard replaces what a device holds, so an old copy never outlives an update. A device may paint from what it holds, but it always fetches fresh copies in the background, and a stored file that fails to refresh never turns a working file into an error. Any change put out reaches every browser and installed app within two visits, slow phone connections included, whether or not the version number changed.

### Installing needs a secure address and an admin can check each step

The dashboard is reachable over https wherever phones use it, and every "open the dashboard" link follows the site's dashboard address. What a phone needs to install the dashboard and Timeline Cards as apps is reachable without signing in; the server checks this fact on its own and raises a serious problem when it is broken, saying the fix needs a change to the product itself.

An admin can check an address for installing the dashboard as an app. The checks run in order and stop at the first failure, one line each (OK, FAIL or SKIP):

1. the address is secure (https; otherwise "no secure context: no offline worker, no install prompt");
2. its certificate is accepted;
3. the app description can be read signed out and has a start page and icons (otherwise "the browser will not offer to install it");
4. the offline page's helper is served and allowed;
5. the address answers as the dashboard, with a version (otherwise "whatever is behind this address, it is not the dashboard");
6. every sign-in cookie is marked secure, or the ones that are not are named with the fix.

It ends "STOPPED at <check>. Fix that and run this again." when one fails.

- Who: an admin.

### Every page works at phone and tablet width

At phone width (390 pixels) and tablet width (768 pixels), measured against what is actually visible on the device, no page scrolls sideways as a whole and nothing runs past the edge, apart from a table deliberately made to scroll or a form field. Tables become labelled rows. Every button, link and field is at least 44 pixels each way, and no text is smaller than 12 pixels. On a phone, ticking a project is one tap from every place that asks the person to tick one.

- Phone and desk: tables become labelled rows on a phone.

#### Lessons

- Met: DSH-131, DSH-132, DSH-133, DSH-134, DSH-135, DSH-136, DSH-137.

## Security of pages

### Nothing is reachable without signing in except what must be

Only the pages named as open are reachable without signing in: the sign-in page itself, the offline page, what a phone needs to install the dashboard as an app, and the links handed to clients. Each such exception belongs to the page it exists for and goes with it; nothing else is reachable signed out.

### A change that did not come from the dashboard's own page is refused

A change sent to the dashboard from another web site, or from a page whose sign-in has changed since it was drawn, is refused with "this action did not come from this dashboard's own page: reload the page and try again". Timeline Cards shows its own sentence for the same refusal (see Timeline Cards: the editor: Speed and smoothness, "An edit is refused only for a real reason, and never in silence"). The cure is to reload the page. On anything that changes data or drives the editing program, a request whose browser hides where it came from is refused unless it can be shown to come from the dashboard itself; only a request that states no origin at all, as programs do, may pass on its sign-in alone.

### Sign-in travels only over secure connections when the address is secure

When the dashboard's address starts with https, a person's sign-in is only ever carried over secure connections; otherwise it follows whether each visit arrived securely. The address of a visitor that the server records (for limits on failed sign-ins and in its records) is the visitor's real address: the server believes an address passed on by another machine only when the site trusts that machine.

### The dashboard warns when a computer reaches it unencrypted over the public internet

For each computer the dashboard records whether it connects unencrypted over the public internet, unencrypted over the studio's own or private network, or encrypted, and records a change when one happens. Only an unencrypted connection over the public internet is raised to admins; that problem, how serious it is, how often it repeats and its fix are described with the rule it guards (see Accounts, privacy and the legal paperwork: How secrets and keys are kept, "A credential never crosses the internet unencrypted").

### Oversized requests are refused before they are read

Every request is checked for a valid sign-in before anything it carries is read, and reading stops at a hard limit on size whatever length the request declares. Anything larger is refused at once with "request body too large (max N bytes)". A part that takes large files (music, published builds) states its own limit to the person.

### Help pages show only what is published for the person reading them

The help viewer serves only the help pages published for that person's audience, refuses anything outside the help, and keeps links between help pages working.

### Error pages show only what kind of error happened

A page that fails shows only the kind of error and that the detail is kept for the admin. It never shows a storage address, a sign-in name or a folder on the server. Only the admin's problem notice carries the error's message, with secrets masked and its length limited.

#### Lessons

- Met: DSH-138, DSH-139, DSH-140, DSH-141, DSH-142.

## Stopping and resuming the fleet

### An admin stops syncing on every computer at once, with a reason

The stop control explains the whole effect before anything is stopped: every transfer stops on every editor's computer (uploads, downloads, project files, the shared libraries and the first set-up of any new folder); shared work running anywhere goes back to waiting and no computer takes any; no computer starts taking part in Timeline Cards; nothing is deleted and it is fully reversible; and a computer that is off right now takes the stop the moment it reports again.

To stop, the admin gives a reason, which is shown in every editor's app, and chooses how long the stop lasts. Then "stop all syncing" asks the admin to confirm, naming the same whole effect, that nothing is deleted, and that work done while it is stopped reaches no one until syncing starts again. The reason's limits, the refusal without one, the length (24 hours unless the admin chooses another), the stop ending by itself and what each computer and editor sees are described in full with the stop itself (see Sync: Studio-wide stops and the editor's pause, "An admin stops syncing on every computer with a reason").

The stop survives a dashboard restart. Editors cannot start syncing again from their own computers; only an admin can.

- Who: an admin starts it. Anyone signed in, and any recognised computer, can see whether it is on.

### An admin keeps the stop on for longer or starts syncing again

While stopped, the stop control shows "Syncing is stopped on every computer", the reason, "set by <who> <ago> (N hours so far, N computers in the fleet)", and "releases itself <in ...> unless you keep it stopped (kept on N times)", with a line saying that each app picks the stop up on its next report and shows the reason, and that editors cannot start syncing again themselves; only this button can.

- "start syncing again" ends the stop everywhere.
- "keep it stopped" asks the admin to confirm and moves only the end, by the chosen length from now, keeping the reason, who set it and when it began. Asked after the stop has already ended, it is refused (see Sync: Studio-wide stops and the editor's pause, "An admin keeps a studio-wide stop going or starts syncing again").

- Who: an admin.

### Everyone signed in sees the stop on every page

While syncing is stopped across the studio, every signed-in person sees on every page a "stopped" state: "Every computer has stopped syncing because an admin stopped the fleet.", "Syncing is stopped on every computer (N hours so far, M computers in the fleet).", the reason the admin typed, and "Set by <who> <time ago>; it releases itself <in Xh Ym> unless somebody keeps it on." M counts every computer of the studio, including ones switched off. Hours are whole hours since it was set. The release time reads "any moment now" under one minute, then "in Nm", "in Nh Nm", "in Nd Nh". Admins also get "Start syncing again", which takes them to the stop control. The line is re-read every minute while the page is in view; nothing is shown while syncing is normal.

- Who: anyone signed in.
- Ways in: every page, the list of computers, the stop control itself, a shortcut on the overview, and a person's own settings.

### After a stop runs out everyone is told it ended

After a stop has run out, every signed-in person sees an "expired" state: "The fleet-wide stop has expired and syncing has started again everywhere.", "It was set for: <reason>", "Set by <who> <ago>, expired <ago>." The stop control reads "The last stop EXPIRED and syncing started again everywhere <ago>. It was set by <who> <ago>: <reason>." Admins get "Take this notice down" ("ok, it can stay off"), which takes the notice down everywhere without changing any computer; if someone set a new stop meanwhile, nothing is changed: "a new stop was set since this page loaded, so nothing was changed. Use "Start syncing again" if you mean to end it."

- Who: anyone signed in sees it. An admin takes it down.

### Every stop is kept in a history

The stop control lists previous stops: when, what happened (stopped, kept on, started again, expired), who and why.

- Who: an admin.

#### Lessons

- Met: DSH-144.

