# Decision list, page 21: The Footage Sorter and camera cards, part 3

Stays behind: never shown to the session that rebuilds the product.

6 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 21.1 Who may add and remove the folders the Sorter sorts from, and where?

- **Today:** inside the dashboard the folders to sort from are fixed when the server is set up, and a person who tries to change them on the page is told they are set by the server's configuration. The same Sorter run on its own, with no sign-in, lets anyone add or remove them from the page with "+ folder".
- **Options:** A: an admin adds and removes them from the Sorter page ("+ folder") and sees them in the Sorter's settings; a pasted path is understood whether it is written as the server names it or as the admin's own computer names the shared folders. B: anyone signed in may do it. C: they are set only when the part is switched on, never from the page.
- **Recommended:** A, because it keeps one way to set them, keeps the thing that changes what everyone sees in an admin's hands, and still meets "everything can be set by hand".
- **What you would notice:** with A an admin can point the Sorter at a new folder without anyone touching the server; editors cannot. With B any editor can; with C nobody can after set-up.
- (footage-sorter-and-camera-cards-3-Q1)

### 21.2 Should every Sorter setting be changeable on a screen, and by an admin only?

- **Today:** only the calendar choice, its refresh and start date, the folders to sort from (on its own only) and the card names can be changed on the Sorter's screens; the studio's time zone, time folders, camera labels, the free-space margin, allowing unverified copies, bringing camera proxies and what to do on a name clash are set only when the Sorter is installed, with one studio's own values (its time zone, a start date, its camera labels).
- **Options:** A: every setting is on the Sorter's settings, changed by an admin; card names by anyone signed in; one studio's values become that site's settings, carried over. B: keep most fixed at install, only the calendar and card names on screen.
- **Recommended:** A, since you asked for a manual override of everything and one place a setting comes from.
- **What you would notice:** an admin can change the time zone, camera labels and copy rules from the dashboard without help.
- (footage-sorter-and-camera-cards-3-Q2)

### 21.3 "Show in the file manager" should open the clip's folder on the person's own computer?

- **Today:** "Open in Explorer" asks the computer the Sorter runs on to open its file manager, so it only does anything for someone sitting at that computer; inside the dashboard on the NAS it is refused ("there is no Explorer on the server: the path is in the info pane"); and it works only on Windows. Your ruling asks for "open in source in the app and in Explorer".
- **Options:** A: it opens the person's own Explorer or Finder, through the app on their computer, where that computer can reach the footage; elsewhere (a phone, no app) it shows the clip's place with a Copy button. B: drop it and only show the place with a Copy button.
- **Recommended:** A, because it is what the ruling asks for and the app is on every editor's computer anyway.
- **What you would notice:** with A, pressing it on a studio computer opens their own Explorer or Finder at the clip; with B they paste the path themselves.
- (footage-sorter-and-camera-cards-3-Q3)

### 21.4 Should sizes read the same way on a folder link's page as on the Sorter?

- **Today:** the Sorter shows GB and TB with two decimals under 10 and one from 10; the page a folder link opens shows one decimal under 100 (for example "4.2 GB").
- **Options:** A: one rule everywhere, the Sorter's. B: keep the two rules.
- **Recommended:** A, one way of writing a size.
- **What you would notice:** a client sees "4.23 GB" instead of "4.2 GB" on a link page.
- (footage-sorter-and-camera-cards-3-Q4)

### 21.5 Should every link handed outside the studio be in one list?

- **Today:** the Sorter's folder links (a folder of files to download) and the b-roll archive's client folders (chosen clips to view and download) each have their own list of links, made and switched off in different places.
- **Options:** A: keep both kinds of link, since they do different jobs, but show every link handed outside the studio in one list, each saying its kind, switched off from there. B: two separate lists, as now. C: one kind of link for both.
- **Recommended:** A: an admin sees in one place everything that is out there, without merging two different jobs into one.
- **What you would notice:** an admin checking what has been handed out looks in one list instead of two.
- (footage-sorter-and-camera-cards-3-Q5)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 21.6 | May the tools made only for the people building the Sorter go? | a copy of the Sorter run on one computer with no sign-in, where everyone counts as an admin and its regular work can be switched off; a hidden switch that fills the Sorter with made-up clips; and a tool that takes pictures of every Sorter view from sample data. | A: nobody at the studio uses them, and the copy with no sign-in hands footage to anyone who can reach it. (footage-sorter-and-camera-cards-3-Q6) |

## Your answers

Not yet answered.
