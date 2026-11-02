---
name: video-use-install
description: Install the Automate Leverage fork of video-use into Claude Code (or another agent) — get the code, Python venv, ffmpeg, skill registration, and a real transcription check. Free local Whisper transcription, no API key.
---

# video-use install (Automate Leverage fork)

Use this file only for first-time install or reconnect. For daily editing, read `SKILL.md`. The scripts live in `helpers/`.

## What you're doing

You're setting up a conversation-driven video editor for the user. After install, the user drops raw footage into any folder, opens their agent (`claude`) there, and says "edit these into a launch video." You do the rest by reading `SKILL.md`.

This fork transcribes **locally and for free** with faster-whisper (`helpers/transcribe_local.py`). There is **no API key step**.

Four things must be true when you're done:

1. The `video-use` code sits in a stable folder (`<repo>`), with `SKILL.md` at its root.
2. `<repo>/.venv` has the Python deps (`pip install -e .`).
3. `ffmpeg` and `ffprobe` run.
4. `~/.claude/skills/video-use` points at `<repo>` (whole folder, so `helpers/` sits next to `SKILL.md`).

## Install prompt contract

- Do everything yourself. Ask the user only before installing system software (Python, ffmpeg) or when a command needs their password. Never invent a password.
- Default `<repo>`: `%USERPROFILE%\video-use` on Windows, `~/video-use` on macOS/Linux. If the user already unzipped `video-use.zip` somewhere, use that folder (the one that directly contains `SKILL.md`).
- Detect the OS first. **On Windows run the PowerShell blocks** (via the PowerShell tool, or `powershell -NoProfile -Command "..."` from Git Bash).
- **Every code block below is self-contained**: it sets its own variables and uses absolute paths, because agent shells don't keep variables or the working directory between commands. Keep it that way if you adapt them. If `<repo>` is not the default path, change `$VU` / `VU` in **every** block.
- Verify by running one real transcription on one real file. Don't declare success on file-existence checks alone.

## Steps

### 0. Check prerequisites

Supported Python: **3.10–3.12** (3.12 recommended).

Windows (PowerShell) — use the `py` launcher; plain `python` may be the Microsoft Store stub, which opens the Store or fails with exit code 9009:

```powershell
py -3.12 --version; py --list; git --version; ffmpeg -version | Select-Object -First 1
```

macOS / Linux:

```bash
python3 --version; git --version; ffmpeg -version | head -1
```

- No Python 3.10–3.12: ask, then `winget install --id Python.Python.3.12 -e` (Windows), `brew install python@3.12` (macOS), `sudo apt-get install -y python3 python3-venv` (Debian/Ubuntu — `python3-venv` is needed for `-m venv`).
- No git: that's fine, step 1 has a zip fallback.
- ffmpeg is handled in step 3.

Below, `PYEXE` is the Python you'll create the venv with: `py -3.12` on Windows (or whichever 3.10–3.12 `py --list` shows, e.g. `py -3.11`), `python3` elsewhere.

### 1. Get the code

Windows (PowerShell):

```powershell
$VU = "$env:USERPROFILE\video-use"
if (Test-Path "$VU\SKILL.md") {
  if (Test-Path "$VU\.git") { git -C $VU pull --ff-only } else { "already present (zip copy)" }
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
  git clone https://github.com/alphalifejourney/video-use $VU
} else {
  $zip = "$env:TEMP\video-use.zip"
  Invoke-WebRequest https://github.com/alphalifejourney/video-use/releases/latest/download/video-use.zip -OutFile $zip
  Expand-Archive $zip -DestinationPath $env:USERPROFILE -Force   # zip has a top-level video-use\ folder
  Remove-Item $zip
}
Test-Path "$VU\SKILL.md"   # must print True
```

macOS / Linux:

```bash
VU="$HOME/video-use"
if [ -f "$VU/SKILL.md" ]; then
  [ -d "$VU/.git" ] && git -C "$VU" pull --ff-only || echo "already present (zip copy)"
elif command -v git >/dev/null; then
  git clone https://github.com/alphalifejourney/video-use "$VU"
else
  curl -L -o /tmp/video-use.zip https://github.com/alphalifejourney/video-use/releases/latest/download/video-use.zip
  unzip -q -o /tmp/video-use.zip -d "$HOME" && rm /tmp/video-use.zip
fi
test -f "$VU/SKILL.md" && echo OK
```

If the user unzipped by hand and ended up with `video-use\video-use\SKILL.md` (Windows "Extract All" adds a folder), use the inner folder as `<repo>`.

### 2. Create the venv and install Python deps

Windows (PowerShell):

```powershell
$VU = "$env:USERPROFILE\video-use"
py -3.12 -m venv "$VU\.venv"   # or the PYEXE from step 0, e.g. py -3.11
& "$VU\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$VU\.venv\Scripts\python.exe" -m pip install -e "$VU"
```

macOS / Linux:

```bash
VU="$HOME/video-use"
python3 -m venv "$VU/.venv"
"$VU/.venv/bin/python" -m pip install --upgrade pip
"$VU/.venv/bin/python" -m pip install -e "$VU"
```

This installs `faster-whisper`, `librosa`, `numpy`, `matplotlib`, `pillow`, `requests`, and on Windows/Linux the CUDA 12 runtime wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, about 1 GB — downloaded even without an NVIDIA GPU) so a GPU works with no separate CUDA install. Without an NVIDIA GPU everything still runs on CPU, just slower. Expect a few minutes.

From here on, `<venv-python>` = `<repo>\.venv\Scripts\python.exe` (Windows) or `<repo>/.venv/bin/python` (macOS/Linux).

### 3. Install ffmpeg (+ optional yt-dlp)

`ffmpeg` and `ffprobe` are required. If `ffmpeg -version` fails, **ask the user before installing**, then:

Windows (PowerShell) — winget updates PATH only for new terminals, so refresh it in this session instead of restarting Claude Code:

```powershell
winget install --id Gyan.FFmpeg -e   # winget may ask to accept its source terms: that's the user's call, so run it only after they agree
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
ffprobe -version | Select-Object -First 1
```

If `ffprobe` still isn't found in later tool calls, run that `$env:Path = ...` line at the start of the call; the user's next Claude Code session will see it normally.

macOS / Linux:

```bash
brew install ffmpeg                                        # macOS
sudo apt-get update && sudo apt-get install -y ffmpeg      # Debian / Ubuntu
```

`yt-dlp` is only needed to pull sources from URLs — install it lazily (`<venv-python> -m pip install yt-dlp`) the first time the user asks. Animation engines (HyperFrames, Remotion, Manim) are installed lazily per project, not now. If a package manager needs sudo/admin, tell the user the exact command and wait.

### 4. Register the skill with Claude Code

Windows (PowerShell) — a **directory junction** (regular symlinks need admin or Developer Mode):

```powershell
$VU = "$env:USERPROFILE\video-use"
$LINK = "$env:USERPROFILE\.claude\skills\video-use"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
if (Test-Path $LINK) {
  $t = (Get-Item $LINK).Target
  if ($t -ne $VU) { "existing $LINK points at '$t' - ask the user before replacing it" } else { "already registered" }
} else {
  New-Item -ItemType Junction -Path $LINK -Target $VU | Out-Null; "registered"
}
Test-Path "$LINK\SKILL.md"   # must print True
```

To replace a wrong junction (after the user agrees): `cmd /c rmdir "%USERPROFILE%\.claude\skills\video-use"` removes only the link, not the files it points to; then rerun the block.

macOS / Linux:

```bash
mkdir -p ~/.claude/skills
ln -sfn "$HOME/video-use" ~/.claude/skills/video-use
test -f ~/.claude/skills/video-use/SKILL.md && echo registered
```

Other agents: Codex → link into `${CODEX_HOME:-$HOME/.codex}/skills/video-use` the same way. An agent with no skills directory → import `<repo>/SKILL.md` from its system prompt / `CLAUDE.md`-equivalent.

Claude Code loads new skills when a session starts — the user should restart Claude Code (or open a new session) after you finish.

### 5. API key — none needed

Transcription runs locally. **Do not ask for an API key.**

Optional: if the user explicitly wants ElevenLabs Scribe (paid; adds speaker labels and audio-event tags), they copy `.env.example` to `.env` in `<repo>` and put their key after `ELEVENLABS_API_KEY=`. Never echo the key, never commit `.env` (it's gitignored). `helpers/transcribe.py` / `transcribe_batch.py` then use it.

### 6. Verify end-to-end

Ask the user for one short real clip (any `.mp4`), or the folder of footage they plan to edit. Tell them first: **the first run downloads the Whisper model** from Hugging Face — about **3 GB for `large-v3`** (used on an NVIDIA GPU) or about **500 MB for `small`** (used on CPU). Later runs use the cache. Output goes to `<clip folder>\edit\transcripts\`, never into the repo.

Windows (PowerShell):

```powershell
$VU = "$env:USERPROFILE\video-use"; $env:PYTHONUTF8 = "1"
& "$VU\.venv\Scripts\python.exe" "$VU\helpers\transcribe_local.py" "C:\path\to\clip.mp4"
```

macOS / Linux:

```bash
"$HOME/video-use/.venv/bin/python" "$HOME/video-use/helpers/transcribe_local.py" "/path/to/clip.mp4"
```

- Success: `loaded large-v3 on cuda` (or `...using the small model on cpu`) and then `saved: <name>.json (N words, en)`.
- `cuda unavailable (...)` followed by the CPU fallback is fine. Force CPU with `--device cpu`; best accuracy on CPU (much slower) with `--model large-v3`.
- Harmless warnings: Hugging Face "symlinks not supported" and "unauthenticated requests".
- `failed to allocate memory`: the computer is out of RAM — close heavy apps and rerun.

If the user has no clip handy, run `<venv-python> <repo>/helpers/transcribe_local.py --help` and `<venv-python> -c "import faster_whisper"`, and tell them the model download will happen on their first edit.

### 7. Hand off

Tell the user, in one short message:

- Where the skill is installed (`<repo>`).
- To restart Claude Code, then open it in their footage folder (in the terminal: `cd <footage folder>` then `claude`; in the desktop app: pick that folder).
- That a good first message is *"edit these into a launch video"* or *"inventory these takes and propose a strategy."*
- That everything lands in `<footage folder>\edit\` (final video: `edit\final.mp4`); their original files are never changed.

## Keeping the skill current

- Git install: `git -C <repo> pull --ff-only`. Zip install: download the new zip and extract over the old folder (keep `.venv`).
- If `pyproject.toml` changed, re-run `<venv-python> -m pip install -e <repo>`.

## Cold-start reminders

- Register the **whole directory**, not just `SKILL.md`.
- Always run helpers with the repo's venv python; system python lacks the deps.
- On Windows set `PYTHONUTF8=1` so non-ASCII transcripts don't crash the console.
- Any modern `ffmpeg` (≥ 4.x) works, including static builds.
- Node.js/npm are only needed for HyperFrames or Remotion slots (HyperFrames needs Node.js 22+). Don't install them during setup.
- Linux without a package manager you recognize: print https://ffmpeg.org/download.html and wait.
