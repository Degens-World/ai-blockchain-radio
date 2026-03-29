# AI Blockchain Radio

An open-source AI DJ radio station for crypto communities. Monitors a live blockchain, generates real-time commentary using a local LLM via Ollama, synthesizes speech with Kokoro TTS, and streams everything as HLS audio — no cloud APIs required.

**Live example:** [radio.degens.world](https://radio.degens.world) — built on Ergo

---

## What It Does

- **On-chain monitoring** — watches for new blocks, whale transactions, and token activity in real time
- **AI commentary** — sends chain data to a local Llama/Mistral model; generates live DJ drops
- **Text-to-speech** — converts LLM output to audio using Kokoro TTS (high quality, runs locally)
- **HLS streaming** — pipes audio through FFmpeg into a live HLS stream served over HTTP
- **Segment scheduling** — rotates between top-of-hour, music breaks, dApp spotlights, deep dives, and on-chain alerts
- **Music library** — plays rotating WAV tracks between drops; optionally generates AI music via MusicGen

---

## Prerequisites

### Python 3.10+
```bash
python --version
```

### FFmpeg
**Windows:** `winget install ffmpeg` or `choco install ffmpeg`  
**macOS:** `brew install ffmpeg`  
**Linux:** `sudo apt install ffmpeg`

### Ollama
Install from [ollama.com](https://ollama.com), then pull a model:
```bash
ollama pull mistral-nemo     # recommended — best degen energy
# or
ollama pull llama3.1:8b      # more factually accurate, less chaotic
```

Start it:
```bash
ollama serve
```

### ngrok (for public URL)
Download from [ngrok.com](https://ngrok.com/download) and authenticate:
```bash
ngrok config add-authtoken YOUR_TOKEN
```

---

## Installation

```bash
git clone https://github.com/ArOhBeK/ai-blockchain-radio.git
cd ai-blockchain-radio
pip install -r requirements.txt
cp .env.example .env
# edit .env with your settings
```

---

## Running

**Terminal 1 — Ollama:**
```bash
ollama serve
```

**Terminal 2 — Radio:**
```bash
python radio_live.py
```

**Terminal 3 — Public URL:**
```bash
ngrok http 8234
```

Open `http://localhost:8234` in your browser, or share the ngrok URL.

---

## Configuration

All settings live in `.env`. Key options:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `mistral-nemo:latest` | LLM model for commentary |
| `VOICE` | `am_michael` | Kokoro TTS voice |
| `KOKORO_SPEED` | `1.15` | Speech rate (1.0 = normal) |
| `STREAM_PORT` | `8234` | HTTP server port |
| `COIN_ID` | `ergo` | CoinGecko coin ID for price |
| `WHALE_THRESHOLD` | `10000` | Coin value to trigger whale alert |
| `MUSICGEN_ENABLED` | `false` | Enable AI music generation |
| `FFMPEG` | `ffmpeg` | Path to ffmpeg binary |

See `.env.example` for the full list.

---

## Kokoro Voices

| Voice | Character |
|-------|-----------|
| `am_michael` | Deep, authoritative (default) |
| `am_adam` | Warm, conversational |
| `am_echo` | Crisp, energetic |
| `am_fenrir` | Bold, dramatic |
| `am_puck` | Light, playful |
| `af_bella` | Bright, enthusiastic |
| `af_heart` | Warm, expressive |
| `af_nicole` | Clear, professional |

---

## Customizing the DJ Persona

Edit `DJ_PERSONA` in `radio_live.py`. Tips:
- Be specific about tone — vague instructions produce generic output
- Set length expectations inline (`8-12 sentences`)
- Include factual context about your chain to prevent hallucination
- Name your community and ecosystem explicitly

---

## Segment Schedule

Defined in `radio_schedule.py`. The default schedule (repeating each hour):

| Minutes | Segment |
|---------|---------|
| 0–2 | Top of hour |
| 2–6 | Music |
| 6–8 | dApp spotlight |
| 8–20 | On-chain commentary |
| 20–22 | Market vibes |
| 22–26 | Music |
| 26–28 | Ecosystem report |
| 28–40 | On-chain commentary |
| 40–42 | Community callout |
| 42–46 | Music |
| 46–49 | Deep dive |
| 49–60 | On-chain commentary |

Special segments fire at specific hours (morning briefing at 9am, midday report at noon, etc).

---

## Optional: AI Music with MusicGen

```bash
pip install torch torchaudio transformers accelerate
```

Set in `.env`:
```
MUSICGEN_ENABLED=true
MUSICGEN_MODEL=facebook/musicgen-small
```

Requires a CUDA GPU with 6GB+ VRAM. The script builds a rotating library of generated tracks (`music_library/`) and replenishes it in the background.

---

## Deploying the Player

The player HTML lives at `player.html`. Deploy it anywhere static files are served — GitHub Pages, Netlify, Vercel — then update the `STREAM` URL inside to point to your public ngrok/tunnel URL.

For best results, point a subdomain at your player host:
```
radio.yourdomain.com  →  CNAME  →  yourname.github.io
```

The stream itself needs a stable public HTTPS URL. Options:
- **ngrok free** — URL changes on restart (fine for testing)
- **Cloudflare Tunnel** — free, persistent URL: `cloudflared tunnel --url http://localhost:8234`
- **VPS + Nginx reverse proxy** — full control

---

## Architecture

```
radio_live.py       — main loop: fetch chain data → LLM → Kokoro TTS → FFmpeg HLS
radio_schedule.py   — segment scheduler (what plays when)
player.html         — HLS.js-based browser player
hls_output/         — live .m3u8 playlist + .ts segments
clips/              — TTS output (auto-cleaned)
music_library/      — rotating WAV tracks
```

---

## License

MIT — build your own, fork freely, ship it.

*The chain never sleeps, and neither does the DJ.*
