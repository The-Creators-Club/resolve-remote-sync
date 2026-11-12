# Work handed to the fleet's computers

## When a computer counts as free and able

### JOB-001: Windows reported a person who was typing as idle for seven weeks.
- What was going on: Windows' last-input clock wraps every 49.7 days, idle time is per signed-in session, and an unattended Resolve render looks like an idle computer.
- What the product must do: Idle time stays correct past 49.7 days of uptime, and heavy work never starts on a computer while Resolve is rendering.
- Kind: 1a
- From: G01-023

### JOB-002: Making proxies on the NAS during a card offload halved both.
- What was going on: The NAS disks are one shared bottleneck; reading footage for proxies while a camera-card offload writes cuts both speeds roughly in half.
- What the product must do: Proxy making that reads from the NAS does not run, or yields, while a camera-card offload to the NAS is in progress.
- Kind: 1a
- From: M06-006

### JOB-003: Background work must not land on a computer whose user might be at it.
- What was going on: Guessing "idle" when idleness cannot be measured lands graphics-card work on a person mid-edit; killing a long transcription when they return wastes all of it.
- What the product must do: "Cannot tell if idle" counts as busy; no new job starts while someone is present, and a long job already running is not killed when they return.
- Kind: 3
- From: C03-021

### JOB-004: A computer switched off weeks ago was still offered jobs.
- What was going on: Each computer was judged by its last report however old, so a long-silent machine could win a job or make a job look runnable.
- What the product must do: Only computers that reported recently are offered jobs or counted as able, and a silent computer is named as the reason a job waits.
- Kind: 3
- From: H07-076, H06-017

### JOB-005: A job ran out of graphics memory on a computer busy with its own work.
- What was going on: The longest-idle computer might hold 8-12 GB of model data for local indexing or be encoding, and not all graphics-card users took turns.
- What the product must do: All work on one computer's graphics card takes turns; a computer busy with local graphics work takes no job, says why, and is not put in cool-down for it.
- Kind: 3
- From: L04-153, H07-146

### JOB-006: A computer that could not take a pushed update silently dropped out of jobs.
- What was going on: An update asked for a build withheld from that computer (recalled, wrong processor, needs a newer server), and it was kept from every job for 14 days.
- What the product must do: A computer an update cannot reach stays eligible for every job it can run, and the admin is shown why it was not updated.
- Kind: 3
- From: H06-121, L09-016

## What a computer can honestly offer

### JOB-007: An output name with a colon worked on Mac and failed on Windows.
- What was going on: A colon or backslash is legal in Mac and Linux file names but not on Windows, so "Q&A: interview" failed only when a Windows computer took it.
- What the product must do: Output names are checked against the rules of the computer that will write them; a name invalid only on Windows is refused only there.
- Kind: 1a
- From: H07-073

### JOB-008: A computer took jobs for a drive that was unplugged.
- What was going on: Each computer reaches the shared storage by a different drive or path, and an unplugged drive was still offered; an absolute path also slipped through as relative.
- What the product must do: A computer offers work only for storage it can read now; a job names files relative to that storage, and absolute paths or ".." are refused.
- Kind: 3
- From: C03-022, G01-030

### JOB-009: A laptop claimed media jobs and failed each one within a second.
- What was going on: The ability check found the media program where the app installed it, but the job launched it by bare name and could not find it.
- What the product must do: A computer offers a job kind only after confirming that the exact programs that job will launch can be started.
- Kind: 3
- From: L10-041, H06-027

### JOB-010: Every computer was refused media jobs because a reported ability was dropped.
- What was going on: The server ignored report fields it did not know, so an ability added only on the computer's side was stored as "cannot" for every computer.
- What the product must do: Every ability a computer reports reaches the job offering unchanged; an unrecognised ability is never silently read as "cannot".
- Kind: 3
- From: G01-029

### JOB-011: A computer that failed to install its media tools looked never set up.
- What was going on: A full disk or a Mac's missing certificates stopped the tool install; the cause stayed in that computer's log and the dashboard said only "lacks the tool".
- What the product must do: After two failed installs in a row, the admin sees which tool failed and why, on alerts and on "why is this job waiting".
- Kind: 3
- From: L07-018, L06-012, H05-056

## Choosing who runs what

### JOB-012: Work waiting for an idle computer could not be started on demand.
- What was going on: The owner wanted to "force start" proxy and transcription work "without waiting for someone's idle PC" and see "progress updates in the dashboard".
- What the product must do: An admin can start queued work now on a chosen computer, a person can lend their own computer for 30 minutes, and live progress shows.
- Kind: 2
- From: P09-006, C03-025

### JOB-013: The editor picks which computer makes a clip's proxy, from the preview.
- What was going on: The owner wanted "a dropdown of accessible machines, to send the task to one or another", beside the video preview and on each incoming clip.
- What the product must do: Choosing a computer for any job is a pick from the studio's known computers, typed only when none are known, and sends the work at once.
- Kind: 2
- From: P09-021, D07-024

### JOB-014: Whether a computer does fleet work could be changed only in a text file.
- What was going on: Taking part in shared work, and which kinds, had no control a person could reach on the computer.
- What the product must do: A person can switch shared work on or off and choose kinds; all kinds ticked includes future kinds; work tied to one computer's Resolve is never handed elsewhere.
- Kind: 3
- From: L04-156

## Load on the NAS and the computers

### JOB-015: Opening an edit view must never start dozens of encodes on the NAS.
- What was going on: Every clip in a lane needs playback audio, a picture proxy and a waveform, and the lane cannot play at all without the audio.
- What the product must do: Preview media is made one item at a time per machine, audio before picture, and opening a lane never runs more than one encode per output.
- Kind: 3
- From: D01-051

### JOB-016: A computer with a broken encoder won every retry and limits were overshot.
- What was going on: A machine failing in two seconds is idle again at once; limits counted apart from the claim let simultaneous claims through and saturated the NAS share.
- What the product must do: A computer that just failed waits before another job, and the limit on each heavy kind running at once holds at the moment of every claim.
- Kind: 3
- From: C03-023, L06-031, H05-055

## Progress

### JOB-017: A job whose progress was unknown sat at 0%, which looks stuck.
- What was going on: A job at 0% for minutes reads as wedged, and transcription progress stayed hidden until the very end.
- What the product must do: Progress shows a real percentage when known and "running" when not, never a made-up 0%; long transcriptions report progress as they go.
- Kind: 3
- From: C03-026

## Stopping and cancelling

### JOB-018: A cancelled transcription kept the graphics card busy after "stopped".
- What was going on: Ending a process on Windows does not end the processes it started, so a helper kept writing, held graphics memory or kept a half-downloaded file locked.
- What the product must do: Cancel, stop and quit end every process a job started within seconds, and report done only once all have exited.
- Kind: 1a
- From: H06-028, L10-002

### JOB-019: A cancelled job read "stopped" while it was still writing files.
- What was going on: Marking a job ended while its encoder still ran is how a half-made proxy gets published into the shared folder.
- What the product must do: A cancel shows "stopping" until the computer confirms the work ended; the partial file is removed, and a file already finished is kept.
- Kind: 3
- From: D01-056, C03-024

### JOB-020: Pressing stop at the computer was undone by the next server reply.
- What was going on: The editor's stop was kept where the server's reply overwrote it, so the job ran to completion after the app said stopped.
- What the product must do: A job the editor stops on their own computer stays stopped until it ends, whatever the server sends next.
- Kind: 3
- From: L06-011, H05-053

### JOB-021: The admin's cancel silently did nothing on a computer with old local stops.
- What was going on: Sixteen stale stops pressed at the computer filled a capped list ahead of the admin's cancel, which was the entry cut off.
- What the product must do: An admin's cancel of a running job always reaches that computer, whatever its local history.
- Kind: 3
- From: L07-020

### JOB-022: A job whose source file stalled ignored cancel, stop and its time limit.
- What was going on: Reading from a stalled source blocked indefinitely while the job kept its hold alive, so the computer took no more work until restarted.
- What the product must do: A running job always obeys cancel, a studio-wide stop and its time limit, even when its source stops delivering data.
- Kind: 3
- From: H04-072

### JOB-023: A cancelled job came back and ran on another computer.
- What was going on: A cancel racing a claim reported success over a running job, and a cancelled job whose computer went to sleep was requeued and passed on.
- What the product must do: A cancelled job never runs again anywhere, the cancel reports the state it actually ended in, and the queue count includes only jobs that can be handed out.
- Kind: 3
- From: L07-048, L06-026, H05-054

### JOB-024: A computer that lost a job cancelled it and deleted the new holder's work.
- What was going on: After one computer's hold lapsed and another took over, the first one's late cancel removed the file the new holder had just added.
- What the product must do: Only the computer currently holding a piece of work can cancel or change it; a late word from a former holder changes nothing.
- Kind: 3
- From: H07-105, C04-010

## Outages and withdrawn access

### JOB-025: A three-second server restart killed a running job and blamed the computer.
- What was going on: One failed check-in ended the job, counted an attempt and cooled the computer down, while a real refusal of access mid-run was treated as a passing error.
- What the product must do: A running job survives brief server or network loss and stops only when the server says the job is gone or access is withdrawn.
- Kind: 3
- From: H04-071, L03-086, H07-074

### JOB-026: Suspending an editor mid-job wasted forty minutes of work and threw it away.
- What was going on: The suspended account's computer finished, wrote into shared storage, had its result refused, and the job re-ran elsewhere with nobody told.
- What the product must do: On suspension a running job stops within one check-in, a finished one can still be handed in, and no new work is taken under that account.
- Kind: 3
- From: L07-021

### JOB-027: A barred computer said it was taking work while every request was refused.
- What was going on: The refusal message showed only in one state, and the resting state counted as allowed, so the editor saw nothing to act on.
- What the product must do: While its account is refused, a computer shows it is not taking work and tells the editor to ask the studio; it clears on the next accepted request.
- Kind: 3
- From: L07-022

## Failures, retries and the queue

### JOB-028: A job that could never succeed toured every computer, cooling each down.
- What was going on: A waveform for a video with no audio track failed as "try elsewhere", so it visited every machine; most other failures do belong to the machine.
- What the product must do: A failure about the source ends the job at once with a plain reason; a machine failure is retried elsewhere; a file is ready only once on disk.
- Kind: 3
- From: D01-052, C05-086, H06-026, H07-075

### JOB-029: Two clicks on try again queued the same encode twice.
- What was going on: The duplicate check looked only at the first thousand open jobs, and a 1,200-deep backlog defeated it.
- What the product must do: Try again never queues a second copy of a job already open, however deep the queue.
- Kind: 3
- From: L06-030

### JOB-030: A block of jobs nobody could run starved every job behind it.
- What was going on: Only the first 200 queued jobs were considered, so 200 jobs needing a graphics card no computer had hid a cheap job from every machine.
- What the product must do: A job some computer can run is offered regardless of how many unrunnable jobs are queued ahead of it.
- Kind: 3
- From: H06-025

### JOB-031: Queued work starved and nobody was told.
- What was going on: Jobs no computer could ever run looked the same as jobs waiting for a busy computer, and nothing outside the jobs list said so.
- What the product must do: A job queued over 6 hours with no computer able or allowed to run it raises a warning; ordinary waiting never does.
- Kind: 3
- From: L04-091

### JOB-032: Jobs handed to the server sat in a queue nothing worked.
- What was going on: Jobs the computers gave up on went to the server's own worker, which was not running, so they waited for ever looking "in hand".
- What the product must do: A job is handed only to a worker running now; otherwise it is shown as abandoned, and an admin can see when nothing drains that queue.
- Kind: 3
- From: L08-076, H06-024

### JOB-033: The jobs list said "nothing queued" after twelve jobs had failed.
- What was going on: Only open jobs were listed, so failed and abandoned work was invisible and retrying meant retyping every detail.
- What the product must do: Recent failed and abandoned jobs are listed with their full error and last computer, and try again makes a new job, leaving the old record untouched.
- Kind: 3
- From: L04-086

### JOB-034: A computer's reason for refusing work carried a stale earlier reason along.
- What was going on: A stopped machine read "admin stopped syncing ... Indexing b-roll" because the previous check's reason was never cleared.
- What the product must do: The reason a computer gives for not taking work describes only the current check.
- Kind: 3
- From: L06-014

### JOB-035: A computer taking no shared work could not say why.
- What was going on: The server and the computer each had reasons for not taking work, shown nowhere, so an empty queue looked like a broken computer.
- What the product must do: Each computer states in words whether it is taking work and why not, "nothing offered" reads as taking work, and its current and last ten jobs are visible.
- Kind: 3
- From: L04-116

## Results that are complete and current

### JOB-036: Two machines making the same preview file must not collide.
- What was going on: Another computer and the server can make the same file at the same moment.
- What the product must do: A file appears under its final name only complete, the first finished copy wins, and outputs are named as the editor knows the clip.
- Kind: 3
- From: D01-055

### JOB-037: A stale waveform newer than its footage was never remade.
- What was going on: A waveform in an old format is still newer than its source, so "newer than the source" refused every remake and discarded fresh ones.
- What the product must do: A derived file counts as made only if newer than its source and in the current format and settings, asked the same way before work and before publishing.
- Kind: 3
- From: D01-054, G01-028

### JOB-038: A waveform built from half the audio was saved as complete.
- What was going on: When reading a source over a stalled share had not finished within 30 seconds, the partial waveform was published as success and never remade.
- What the product must do: A derived file is published only after the whole source was read; otherwise the job fails as retryable.
- Kind: 3
- From: H05-057, L06-013

### JOB-039: A finished media job was failed because its log output stalled.
- What was going on: A stalled side stream that carries no media failed a complete decode, and a genuine read error had its message replaced by a generic one.
- What the product must do: A job is judged on whether its real output is complete; a side stream never fails it, and a real error keeps its own message.
- Kind: 3
- From: L07-019

## Sealed

### JOB-S01: A machine lists the hardware encoder and then fails mid-encode.
- What was going on: A machine without a suitable graphics card still lists the hardware encoder; a 64x64 test frame fails even on a real RTX 3080.
- What the product must do: Hardware encoding is used only after a real one-frame encode of at least 320x240 succeeded on that machine.
- Kind: 1b
- Tool: ffmpeg h264_nvenc
- From: C03-029

### JOB-S02: A temporary output name broke the encoder.
- What was going on: The tool picks the format from the extension, so "name.m4a.partial" fails; .m4a, .mp4 and .ogg map to the formats ipod, mp4 and ogg.
- What the product must do: Any output written under a temporary name states its format explicitly, and the result is byte-identical to the normal command.
- Kind: 1b
- Tool: ffmpeg
- From: G01-027

## Removed
