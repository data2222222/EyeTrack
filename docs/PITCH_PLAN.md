# EyeTrack pitch and presentation plan

Planning assumption: a five-minute hackathon/project presentation, followed by questions. This is a script and slide outline, not a finished deck. Product details are based on the current README, desktop flow and extension; rehearse against the final build before presenting.

## The pitch

**One sentence:** EyeTrack helps you stay with a study goal through desktop focus sessions, browser reminders and optional webcam observations.

**The story:** A student sits down to revise physics, opens a useful page, drifts onto a distracting one, gets a reminder of their goal, and finishes with a summary they can reflect on.

**What the audience should remember:** EyeTrack connects the goal you set with what happens during the session, then gives you a chance to return to the task.

### Opening script — about 20 seconds

“You sit down to study for 25 minutes. You open the right page, then another tab, and suddenly you're doing something else. EyeTrack helps you notice that drift during the session. Let us show you one study block, from the goal to the final summary.”

### Standalone pitch — about 45 seconds

“EyeTrack is a desktop focus app for students. You set a goal and start a work block. A Chrome extension supplies website activity, and an optional webcam estimates whether you're looking at the screen, paper, away, or whether a phone is visible. During work, distracting websites show a reminder of your goal and remaining time. Afterwards, you can review your active time and separate camera and computer-activity summaries. Camera frames are never saved or uploaded, and you can use the app without a camera. Our next step is to test whether these reminders actually help students return to their work.”

## Five-minute running order

| Clock | Screen | Purpose |
| --- | --- | --- |
| 0:00–0:20 | Slide 1: EyeTrack | Introduce the study scenario |
| 0:20–0:50 | Slide 2: The study session | Make the problem concrete |
| 0:50–1:10 | Slide 3: The focus loop | Explain the product in one pass |
| 1:10–3:10 | Slide 4, then the live app | Demonstrate one complete journey |
| 3:10–3:45 | Slide 5: How EyeTrack works | Explain the engineering behind what they saw |
| 3:45–4:25 | Slide 6: Privacy and user control | Explain the data boundary and limits |
| 4:25–5:00 | Slide 7: What we test next | State the next step and close |

For two presenters, A owns the story and slides; B operates the app and narrates the demo. Handoff: “Let's try it with a physics revision session.” B returns with: “That's the full loop: a goal, a reminder, and a review.” With one presenter, use the same script and rehearse the app switches.

## What we do during the live demo

Keep the scenario consistent: **“Revise capacitors for my physics exam.”** Use the default 25/5 rhythm and end the session manually; a two-minute demonstration should not depend on a timer completing. Select **Computer only** for the simplest camera demonstration.

Arrange the desktop app and Chrome so both are readable on the projector. Prepare one relevant page and one rehearsed distracting page. Navigate to the distracting page from the relevant page in the same tab, so **Back to studying** has a useful history entry. Use pages without sign-in, autoplay, or personal content.

| Demo time | Operator action | Presenter words / audience takeaway |
| --- | --- | --- |
| 0:00–0:15 | Show setup with the goal already entered. Point to the camera option and click **Start 25-minute session**. | “I'm revising capacitors. I choose my work block and whether to use the camera.” |
| 0:15–0:35 | Stay facing the screen. Show the timer, camera state and current activity. Allow initial tracking to settle. | “The timer tracks the work block. Camera observations and computer activity feed a focus estimate; they don't prove I've learned anything.” |
| 0:35–0:50 | Look clearly away for roughly four seconds, then return. Point to the state change, if observed. | “It can estimate when I look away. Looking away doesn't stop my session clock.” Do not wait for a particular score or popup. |
| 0:50–1:20 | Bring Chrome forward and navigate from the study page to the rehearsed distracting page. Show the focus screen and click **Back to studying**. | “When I drift onto a distracting site, the reminder brings back my goal and the time left. Here I can choose to return.” Name the actual verdict source if discussing it: site list, Jev or cached Jev. |
| 1:20–1:35 | Return to the desktop app. Click **Pause**, show the frozen countdown, then **Resume**. | “I control when work stops. Pausing preserves the work I have left.” |
| 1:35–2:00 | Click **End**, confirm **Yes**, and show the summary. Point to active time and the separate attention/activity breakdowns. | “I'm ending this demo early. This is the time recorded and what the app observed. I can also record whether I reached my goal.” Leave goal completion unanswered, or select an honest response; this demonstration did not complete the revision task. |

The key moment is the distracting page displaying the same goal entered at the start. Give the audience time to read it. The summary closes the story; make sure it gets screen time.

### Optional substitutions, only after rehearsal

- **Phone detection:** replace the look-away segment with a brief phone-in-view demonstration if it reliably works on the presentation laptop. Say “phone detected in view,” not “it knows I'm using my phone.” Check the final alert settings and volume beforehand, then remove the phone promptly. Do not add a long alarm sequence to the main pitch.
- **Paper work:** choose **Computer + paper** and briefly look down at notes, if this is a stronger demonstration for the audience and calibration is reliable.
- **Goal-aware Jev:** replace the basic website segment with a relevant physics video and an unrelated video on the same domain. Explain that Jev uses the goal and page context, so one domain can contain useful and distracting pages. Use only after both verdicts and response times have been rehearsed. A cached verdict must be described as cached; the list fallback does not demonstrate semantic understanding.

Keep settings, calibration, app alerts and blink/yawn estimates for questions. They add branches to a short demonstration without helping the core story.

## Presentation slides plan

Use seven slides with one main visual or idea per slide. Use large text and actual app screenshots where helpful. The quoted copy below goes on the slide; the spoken lines belong in presenter notes. Capture screenshots from a clean rehearsal session, with no credentials or personal browsing visible.

### Slide 1 — EyeTrack

**On-slide copy**

> EyeTrack  
> Stay with the goal you set  
> [Team names]

**Visual:** one large crop of the active-session screen, with the goal and countdown readable. Keep the title area simple.

**Say:** use the opening script above. Introduce the product through a recognizable study moment.

### Slide 2 — The study session

**On-slide copy**

> A study block can drift off course  
> A useful page. Another tab. A different task.  
> The challenge is noticing while there's still time to return.

**Visual:** a simple staged example of the study page and unrelated page, using clean browser captures. Label the scenario as an example.

**Say:** “Our starting user is a student revising on a laptop. The same browser contains the lesson and the distraction. We wanted to connect the goal they started with to a reminder during the session.” This is the product premise, not a claim established by user research.

### Slide 3 — The focus loop

**On-slide copy**

> Set a goal → Work → Notice drift → Return → Review  
> Desktop sessions · Chrome reminders · Optional camera

**Visual:** one readable horizontal sequence; avoid filling the slide with feature screenshots.

**Say:** “EyeTrack puts these steps in one desktop flow. It combines website activity with optional camera observations, then lets the user review the session. We'll show that loop now.”

### Slide 4 — A physics revision session

**On-slide copy**

> Goal: Revise capacitors for my physics exam  
> Start a block → Visit a distracting page → Return → Review

**Visual:** the setup screen with the goal entered. Then switch to the live app for the two-minute runbook.

**Say:** “Follow the goal through the demo. You'll see it at the start, again in the browser reminder, and in the session review.”

**Backup:** have a short recording of this exact journey ready. Keep it separate from the slide if embedding introduces playback risk. Clearly label playback as a recorded demonstration.

### Slide 5 — How EyeTrack works

**On-slide copy**

> Chrome extension → Local Python engine → Desktop session  
> Optional webcam → Local observation processing  
> Optional Jev → Page classification against the goal

**Visual:** a small architecture diagram with a clear laptop boundary. Keep Jev outside that boundary; label its outgoing input **goal + page context**, never camera frames.

**Say:** “The Chrome extension talks to Python over a loopback connection. The PySide6 app presents the session and summary. Camera processing stays on the laptop. Jev is an optional external classifier; without it, site-list fallback keeps the core session usable.” Do not claim the fallback makes the same goal-aware decisions.

### Slide 6 — Privacy and user control

**On-slide copy**

> Camera optional  
> Frames never saved or uploaded  
> Pause and break are explicit  
> Focus scores are estimates

**Visual:** one clean crop of the camera option or pause controls. Include a readable note: **Optional Jev sends goal and page context; never frames.**

**Say:** “The camera runs only during camera-enabled work and stops on pause, break or session end. You can also work without it. The focus score summarizes observed signals; it cannot tell us whether someone understood a lesson or did productive work. If Jev is enabled, the documented goal and page context leave the device. Camera frames do not.”

### Slide 7 — What we test next

**On-slide copy**

> Next: test with students in real study sessions  
> Do reminders help them return to the task?  
> How often are reminders wrong or unwelcome?  
> [Confirmed demo/repository link or QR code]

**Visual:** a calm closing slide with the product name and a verified link. Leave the link out until the team has chosen a destination that the audience can access.

**Say:** “We've built the session flow, browser reminders and optional camera observations. Next we want to test whether the reminders help students return to work, and where the observations get it wrong. EyeTrack helps you notice when a study session drifts and gives you a chance to return to the goal you set.”

If recruiting testers is the purpose of the event, finish with: “We'd like students to try it and tell us when it helps—and when it interrupts.” Otherwise, finish with “Thank you” and invite questions.

## Rehearsal and presentation setup

1. Choose the final demo build before recording backups. Rehearse on the presentation laptop, with its actual screen-sharing/projector setup. The runbook is planned from the repository, not a verified hardware rehearsal.
2. Complete setup, permissions and model downloads beforehand. Start one engine, reload the extension and demo tabs, and confirm **Chrome connected**.
3. Run a rehearsal session to check lighting, calibration, camera transitions, the selected distracting page, back navigation and summary. Then return to a clean setup screen. Calibration may need repeating after the camera or seating position changes.
4. Test the final sound/alert settings at a comfortable volume. Close distracting apps and silence unrelated OS notifications.
5. Prepare a clearly labelled recording of the full journey and a few clean screenshots: setup, active session, focus screen and summary. Keep raw reports, caches, API keys and configuration files out of presentation assets and version control.
6. Practice the five-minute presentation twice. First verify actions; then use a stopwatch and cut extra narration. Aim to finish slightly early.

### If something fails on stage

| Problem | Immediate response |
| --- | --- |
| Camera fails or readings are unreliable | Say “We'll show the camera-free flow,” disable the camera for a new session, and continue with browser activity. Use the labelled recording if restarting would overrun. |
| Browser reminder does not appear within about five seconds | Switch to the prepared recording of that moment. Say it is recorded; do not debug Chrome on stage. |
| Jev is slow or unavailable | Use the rehearsed list-based page, or the recording. Explain that goal-aware classification is optional. |
| App crashes or screen sharing fails | Use the backup recording/screenshots and narrate the same story. If using screenshots, describe the transitions rather than presenting them as live. |
| Time is running out | Skip pause/resume, go straight to **End → Yes → summary**, then close. |

`--no-camera` supplies **simulated test input**, not genuine camera-free tracking. If using it, explicitly label it simulated. Turning the setup camera option off is the genuine camera-free flow.

## Likely questions

**“How is this different from a timer?”**  
“Alongside the timer, we connect the session goal to browser reminders and combine computer activity with optional camera observations in a review.”

**“Can it tell whether I'm productive?”**  
“No. It estimates observable states and website/app categories. Learning and productivity need other evidence; goal completion is a self-report.”

**“Does it work offline?”**  
“After setup and model downloads, the local session and camera processing do not require Jev. Site lists remain available without a key or network; online page content still needs its own connection.”

**“What leaves my laptop?”**  
“Camera frames never do. With optional Jev enabled, the goal, domain, trimmed URL path, page title and browser name are sent for classification. Privacy filters exclude incognito and protected categories. Local session reports are saved on the computer.”

**“What happens when it is wrong?”**  
“Camera signals can be wrong, especially with lighting, glasses or positioning. Users can pause or work without the camera; the browser reminder offers a temporary bypass. We still need to test false reminders in real sessions.”

**“Have you proved that it improves focus?”**  
“Not yet. We have a working prototype. The next step is to evaluate reminder usefulness, false reminders and whether students return to the task.” Do not present automated software tests as evidence of attention accuracy or improved study outcomes.

## Three-minute version

Use slides **1, 2, 4, 6 and 7**. Spend 15 seconds opening, 20 seconds on the problem, 90 seconds demonstrating start → distracting page → summary, 25 seconds on privacy and 30 seconds closing. Omit the camera-state demonstration, pause/resume and architecture explanation. Keep the same study scenario and backup recording.

## Claims to keep out of the pitch

- Precise screen-coordinate eye tracking, mind reading, or proof of productivity.
- Validated accuracy percentages, improved grades, user counts, traction or performance gains without supporting evidence.
- “Everything stays local” while optional Jev is enabled; describe the actual boundary instead.
- Claims that camera absence automatically pauses time, that breaks auto-resume, or that the focus screen makes distraction impossible.
- A medical interpretation of blink, yawn or sleepiness estimates.
- Unfinished features presented as shipped behavior. Add new features to the main demo only after rehearsing the final build.
