# Video Editor v2

I'm building this to see whether it can find something worth watching in a long gaming recording. That could be something funny, some action, an interesting bit of commentary, or anything else with a clear point to it.

The first job is choosing the moment. I don't want it filling a ten-minute video just because ten minutes was the target.

Right now it's a local browser app for reviewing possible clips. It lines up transcript chunks and sampled frames, looks more closely around promising ranges, and gives a reason for each suggestion. It can also say there isn't enough evidence, or that nothing in the sample is worth keeping. You can check the range in the original video, adjust its boundaries, and save a keep/reject decision.

**The AI's editing judgment is still unproven.** The tests check the code and spending controls. They don't prove it can pick a good clip. Real analysis needs your own OpenAI key; the demo dialogue and diagrams are clearly marked as synthetic.

## Run it

This is a Windows prototype. It uses Python 3.11+, FFmpeg/ffprobe and a browser. Node.js is only needed for the JavaScript checks. It hasn't been tested on other operating systems.

Install Python from [python.org](https://www.python.org/downloads/) and FFmpeg from the builds linked by [ffmpeg.org](https://ffmpeg.org/download.html). Put `ffmpeg` and `ffprobe` on your PATH, then from this folder run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8765`. The synthetic examples work without footage or an API key. Starting the app does not make API calls. It binds to localhost, with no background service or autostart. Ctrl+C stops it. If another copy is already using that port, stop that copy first.

## Try a recording

The current test window is fixed at **02:00-08:00**. The recording needs to be at least eight minutes long and have an audio track.

Stop the app, set your recording path in the same PowerShell session, and prepare the sample:

```powershell
$env:VIDEO_EDITOR_SOURCE = (Resolve-Path '.\my-recording.mp4').Path
.\.venv\Scripts\python.exe prepare_local.py
.\.venv\Scripts\python.exe app.py
```

Use your own filename or full path. If FFmpeg isn't on PATH, set `VIDEO_EDITOR_FFMPEG` and `VIDEO_EDITOR_FFPROBE` to the executable paths in that session too. No paths or credentials need to go in source control.

Preparation extracts twelve small stills and up to three audio tracks. It leaves the original alone and doesn't upload anything. It refuses to replace an existing prepared sample. There is no full-video transcode.

In the app, listen to the prepared tracks and choose the one with the dialogue you want reviewed. Enter your OpenAI key locally, then start the six-minute analysis. The key is cleared from the field and isn't saved. You can also supply `OPENAI_API_KEY` to the app process yourself.

Only the selected audio sample and small stills are sent to OpenAI. The original stays local. The first pass proposes up to three ranges; a second pass gets denser stills around those ranges and can reject them. There are no Google uploads.

Review any suggestions in the actual source with sound. You can save notes and adjusted timestamps, then download the reviewed ranges as JSON. Saving a decision doesn't start a render. An earlier local renderer is included in `render_local.py`, but it isn't connected to this review flow yet and needs a manually supplied edit list.

## Current limits

- Transcripts are timed in 30-second chunks, not word by word. Recognition can be wrong or split a sentence.
- A still every 30 seconds can miss a quick event. Denser samples help, but aren't a complete understanding of the video.
- Loudness and motion aren't enough to call something interesting. Suggestions need a reason and supporting evidence.
- Audio track roles need checking. Browser playback and audio synchronization still need a proper visual/listening pass.
- A rejected six-minute sample doesn't mean the rest of the recording is empty.
- There is no automatic final edit, caption pass or publishing workflow.

The app currently uses `gpt-transcribe` and `gpt-5.4-mini`. Prices in the code were checked against the official model docs on 23 October 2026: [transcription](https://developers.openai.com/api/docs/models/gpt-transcribe) and [editorial analysis](https://developers.openai.com/api/docs/models/gpt-5.4-mini). Model access and current prices need checking before a paid run.

## Spending

The trial has a $5 cap, with each request reserved in a local ledger before it is sent. A sample needs $0.50 of remaining room for the conservative plan. Uncertain requests keep their reservation and stop further calls; there are no automatic retries. A saved editorial run also blocks an accidental duplicate.

That ledger belongs to this checkout. Don't delete it or start another checkout to get around the cap. Tests use isolated fake ledgers and don't call OpenAI.

## Checks and next step

```powershell
.\.venv\Scripts\python.exe -m unittest test_editorial test_interface test_prepare -v
.\.venv\Scripts\python.exe validate_budget.py
node --check app.js
node test_ui.js
```

The Python tests generate their own synthetic media bytes and images. The UI checks use an in-memory DOM, not a real browser. No recording or API key is needed for either.

The next test is simple: run one real sample, get a few timecoded suggestions with reasons, and watch them. If none of them are worth keeping, that's useful to know before spending time on a final edit.

Footage, generated clips, transcripts, extracted frames, local review records, keys and logs are excluded from this repository. No license has been selected yet.
