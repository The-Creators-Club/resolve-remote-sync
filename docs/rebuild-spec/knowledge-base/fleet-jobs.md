# Work shared out across the computers: what real use taught

39 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## When a computer counts as free and able

### JOB-001: Windows reported a person who was typing as idle for seven weeks.
- Why: Windows' last-input clock wraps every 49.7 days, idle time is per signed-in session, and an unattended Resolve render looks like an idle computer.
- Must: Idle time stays correct past 49.7 days of uptime, and heavy work never starts on a computer while Resolve is rendering.
- Kind: given

### JOB-002: Making proxies on the NAS during a card offload halved both.
- Why: The NAS disks are one shared bottleneck; reading footage for proxies while a camera-card offload writes cuts both speeds roughly in half.
- Must: Proxy making that reads from the NAS does not run, or yields, while a camera-card offload to the NAS is in progress.
- Kind: given

### JOB-003: Background work must not land on a computer whose user might be at it.
- Why: Guessing "idle" when idleness cannot be measured lands graphics-card work on a person mid-edit; killing a long transcription when they return wastes all of it.
- Must: "Cannot tell if idle" counts as busy; no new job starts while someone is present, and a long job already running is not killed when they return.
- Kind: situation

### JOB-004: A computer switched off weeks ago was still offered jobs.
- Why: Each computer was judged by its last report however old, so a long-silent machine could win a job or make a job look runnable.
- Must: Only computers that reported recently are offered jobs or counted as able, and a silent computer is named as the reason a job waits.
- Kind: situation

### JOB-005: A job ran out of graphics memory on a computer busy with its own work.
- Why: The longest-idle computer might hold 8-12 GB of model data for local indexing or be encoding, and not all graphics-card users took turns.
- Must: All work on one computer's graphics card takes turns; a computer busy with local graphics work takes no job, says why, and is not put in cool-down for it.
- Kind: situation

### JOB-006: A computer that could not take a pushed update silently dropped out of jobs.
- Why: An update asked for a build withheld from that computer (recalled, wrong processor, needs a newer server), and it was kept from every job for 14 days.
- Must: A computer an update cannot reach stays eligible for every job it can run, and the admin is shown why it was not updated.
- Kind: situation

## What a computer can honestly offer

### JOB-007: An output name with a colon worked on Mac and failed on Windows.
- Why: A colon or backslash is legal in Mac and Linux file names but not on Windows, so "Q&A: interview" failed only when a Windows computer took it.
- Must: Output names are checked against the rules of the computer that will write them; a name invalid only on Windows is refused only there.
- Kind: given

### JOB-008: A computer took jobs for a drive that was unplugged.
- Why: Each computer reaches the shared storage by a different drive or path, and an unplugged drive was still offered; an absolute path also slipped through as relative.
- Must: A computer offers work only for storage it can read now; a job names files relative to that storage, and absolute paths or ".." are refused.
- Kind: situation

### JOB-009: A laptop claimed media jobs and failed each one within a second.
- Why: The ability check found the media program where the app installed it, but the job launched it by bare name and could not find it.
- Must: A computer offers a job kind only after confirming that the exact programs that job will launch can be started.
- Kind: situation

### JOB-010: Every computer was refused media jobs because a reported ability was dropped.
- Why: The server ignored report fields it did not know, so an ability added only on the computer's side was stored as "cannot" for every computer.
- Must: Every ability a computer reports reaches the job offering unchanged; an unrecognised ability is never silently read as "cannot".
- Kind: situation

### JOB-011: A computer that failed to install its media tools looked never set up.
- Why: A full disk or a Mac's missing certificates stopped the tool install; the cause stayed in that computer's log and the dashboard said only "lacks the tool".
- Must: After two failed installs in a row, the admin sees which tool failed and why, on alerts and on "why is this job waiting".
- Kind: situation

## Choosing who runs what

### JOB-012: Work waiting for an idle computer could not be started on demand.
- Why: The owner wanted to "force start" proxy and transcription work "without waiting for someone's idle PC" and see "progress updates in the dashboard".
- Must: An admin can start queued work now on a chosen computer, a person can lend their own computer for 30 minutes, and live progress shows.
- Kind: ruling

### JOB-013: The editor picks which computer makes a clip's proxy, from the preview.
- Why: The owner wanted "a dropdown of accessible machines, to send the task to one or another", beside the video preview and on each incoming clip.
- Must: Choosing a computer for any job is a pick from the studio's known computers, typed only when none are known, and sends the work at once.
- Kind: ruling

### JOB-014: Whether a computer does fleet work could be changed only in a text file.
- Why: Taking part in shared work, and which kinds, had no control a person could reach on the computer.
- Must: A person can switch shared work on or off and choose kinds; all kinds ticked includes future kinds; work tied to one computer's Resolve is never handed elsewhere.
- Kind: situation

## Load on the NAS and the computers

### JOB-015: Opening an edit view must never start dozens of encodes on the NAS.
- Why: Every clip in a lane needs playback audio, a picture proxy and a waveform, and the lane cannot play at all without the audio.
- Must: Preview media is made one item at a time per machine, audio before picture, and opening a lane never runs more than one encode per output.
- Kind: situation

### JOB-016: A computer with a broken encoder won every retry and limits were overshot.
- Why: A machine failing in two seconds is idle again at once; limits counted apart from the claim let simultaneous claims through and saturated the NAS share.
- Must: A computer that just failed waits before another job, and the limit on each heavy kind running at once holds at the moment of every claim.
- Kind: situation

## Progress

### JOB-017: A job whose progress was unknown sat at 0%, which looks stuck.
- Why: A job at 0% for minutes reads as wedged, and transcription progress stayed hidden until the very end.
- Must: Progress shows a real percentage when known and "running" when not, never a made-up 0%; long transcriptions report progress as they go.
- Kind: situation

## Stopping and cancelling

### JOB-018: A cancelled transcription kept the graphics card busy after "stopped".
- Why: Ending a process on Windows does not end the processes it started, so a helper kept writing, held graphics memory or kept a half-downloaded file locked.
- Must: Cancel, stop and quit end every process a job started within seconds, and report done only once all have exited.
- Kind: given

### JOB-019: A cancelled job read "stopped" while it was still writing files.
- Why: Marking a job ended while its encoder still ran is how a half-made proxy gets published into the shared folder.
- Must: A cancel shows "stopping" until the computer confirms the work ended; the partial file is removed, and a file already finished is kept.
- Kind: situation

### JOB-020: Pressing stop at the computer was undone by the next server reply.
- Why: The editor's stop was kept where the server's reply overwrote it, so the job ran to completion after the app said stopped.
- Must: A job the editor stops on their own computer stays stopped until it ends, whatever the server sends next.
- Kind: situation

### JOB-021: The admin's cancel silently did nothing on a computer with old local stops.
- Why: Sixteen stale stops pressed at the computer filled a capped list ahead of the admin's cancel, which was the entry cut off.
- Must: An admin's cancel of a running job always reaches that computer, whatever its local history.
- Kind: situation

### JOB-022: A job whose source file stalled ignored cancel, stop and its time limit.
- Why: Reading from a stalled source blocked indefinitely while the job kept its hold alive, so the computer took no more work until restarted.
- Must: A running job always obeys cancel, a studio-wide stop and its time limit, even when its source stops delivering data.
- Kind: situation

### JOB-023: A cancelled job came back and ran on another computer.
- Why: A cancel racing a claim reported success over a running job, and a cancelled job whose computer went to sleep was requeued and passed on.
- Must: A cancelled job never runs again anywhere, the cancel reports the state it actually ended in, and the queue count includes only jobs that can be handed out.
- Kind: situation

### JOB-024: A computer that lost a job cancelled it and deleted the new holder's work.
- Why: After one computer's hold lapsed and another took over, the first one's late cancel removed the file the new holder had just added.
- Must: Only the computer currently holding a piece of work can cancel or change it; a late word from a former holder changes nothing.
- Kind: situation

## Outages and withdrawn access

### JOB-025: A three-second server restart killed a running job and blamed the computer.
- Why: One failed check-in ended the job, counted an attempt and cooled the computer down, while a real refusal of access mid-run was treated as a passing error.
- Must: A running job survives brief server or network loss and stops only when the server says the job is gone or access is withdrawn.
- Kind: situation

### JOB-026: Suspending an editor mid-job wasted forty minutes of work and threw it away.
- Why: The suspended account's computer finished, wrote into shared storage, had its result refused, and the job re-ran elsewhere with nobody told.
- Must: On suspension a running job stops within one check-in, a finished one can still be handed in, and no new work is taken under that account.
- Kind: situation

### JOB-027: A barred computer said it was taking work while every request was refused.
- Why: The refusal message showed only in one state, and the resting state counted as allowed, so the editor saw nothing to act on.
- Must: While its account is refused, a computer shows it is not taking work and tells the editor to ask the studio; it clears on the next accepted request.
- Kind: situation

## Failures, retries and the queue

### JOB-028: A job that could never succeed toured every computer, cooling each down.
- Why: A waveform for a video with no audio track failed as "try elsewhere", so it visited every machine; most other failures do belong to the machine.
- Must: A failure about the source ends the job at once with a plain reason; a machine failure is retried elsewhere; a file is ready only once on disk.
- Kind: situation

### JOB-029: Two clicks on try again queued the same encode twice.
- Why: The duplicate check looked only at the first thousand open jobs, and a 1,200-deep backlog defeated it.
- Must: Try again never queues a second copy of a job already open, however deep the queue.
- Kind: situation

### JOB-030: A block of jobs nobody could run starved every job behind it.
- Why: Only the first 200 queued jobs were considered, so 200 jobs needing a graphics card no computer had hid a cheap job from every machine.
- Must: A job some computer can run is offered regardless of how many unrunnable jobs are queued ahead of it.
- Kind: situation

### JOB-031: Queued work starved and nobody was told.
- Why: Jobs no computer could ever run looked the same as jobs waiting for a busy computer, and nothing outside the jobs list said so.
- Must: A job queued over 6 hours with no computer able or allowed to run it raises a warning; ordinary waiting never does.
- Kind: situation

### JOB-032: Jobs handed to the server sat in a queue nothing worked.
- Why: Jobs the computers gave up on went to the server's own worker, which was not running, so they waited for ever looking "in hand".
- Must: A job is handed only to a worker running now; otherwise it is shown as abandoned, and an admin can see when nothing drains that queue.
- Kind: situation

### JOB-033: The jobs list said "nothing queued" after twelve jobs had failed.
- Why: Only open jobs were listed, so failed and abandoned work was invisible and retrying meant retyping every detail.
- Must: Recent failed and abandoned jobs are listed with their full error and last computer, and try again makes a new job, leaving the old record untouched.
- Kind: situation

### JOB-034: A computer's reason for refusing work carried a stale earlier reason along.
- Why: A stopped machine read "admin stopped syncing ... Indexing b-roll" because the previous check's reason was never cleared.
- Must: The reason a computer gives for not taking work describes only the current check.
- Kind: situation

### JOB-035: A computer taking no shared work could not say why.
- Why: The server and the computer each had reasons for not taking work, shown nowhere, so an empty queue looked like a broken computer.
- Must: Each computer states in words whether it is taking work and why not, "nothing offered" reads as taking work, and its current and last ten jobs are visible.
- Kind: situation

## Results that are complete and current

### JOB-036: Two machines making the same preview file must not collide.
- Why: Another computer and the server can make the same file at the same moment.
- Must: A file appears under its final name only complete, the first finished copy wins, and outputs are named as the editor knows the clip.
- Kind: situation

### JOB-037: A stale waveform newer than its footage was never remade.
- Why: A waveform in an old format is still newer than its source, so "newer than the source" refused every remake and discarded fresh ones.
- Must: A derived file counts as made only if newer than its source and in the current format and settings, asked the same way before work and before publishing.
- Kind: situation

### JOB-038: A waveform built from half the audio was saved as complete.
- Why: When reading a source over a stalled share had not finished within 30 seconds, the partial waveform was published as success and never remade.
- Must: A derived file is published only after the whole source was read; otherwise the job fails as retryable.
- Kind: situation

### JOB-039: A finished media job was failed because its log output stalled.
- Why: A stalled side stream that carries no media failed a complete decode, and a genuine read error had its message replaced by a generic one.
- Must: A job is judged on whether its real output is complete; a side stream never fails it, and a real error keeps its own message.
- Kind: situation
