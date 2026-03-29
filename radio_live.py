"""
Degens.World Radio — Live Streaming Pipeline
One continuous FFmpeg process fed via PCM pipe — no gaps between drops.
Listen at: http://localhost:8080/stream.m3u8
"""

from dotenv import load_dotenv
load_dotenv()
import asyncio
import queue
import requests
import soundfile as sf
import numpy as np
from kokoro import KPipeline
import re
import os
import subprocess
import threading
import http.server
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from radio_schedule import (
    Segment, get_current_segment, get_segment_prompt,
    get_music_prompt, DAPP_LIST
)

# Config
ERGO_EXPLORER_V1 = "https://api.ergoplatform.com/api/v1"
ERGO_EXPLORER_V0 = "https://api.ergoplatform.com/api/v0"
ERGEXPLORER_ADDRESSBOOK = "https://api.ergexplorer.com/addressbook/getAddresses"
WHALE_ERG = 10_000
TOKEN_ALERT_MIN = 3
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral-nemo:latest")
POLL_INTERVAL = 45
STREAM_PORT = int(os.getenv("STREAM_PORT", "8234"))
HLS_DIR = Path(os.getenv("HLS_DIR", "./hls_output"))
CLIPS_DIR = Path(os.getenv("CLIPS_DIR", "./clips"))
MUSIC_LIBRARY_DIR = Path(os.getenv("MUSIC_DIR", "./music_library"))
MUSIC_LIBRARY_TARGET = 20  # build up to this many songs then rotate
VOICE = os.getenv("VOICE", "am_michael")           # Kokoro voice — am_michael, am_adam, am_echo, am_puck
KOKORO_SPEED = 1.15           # Slightly faster than default for DJ energy
_kokoro: KPipeline = None     # Initialized on first use
FFMPEG = os.getenv("FFMPEG", "ffmpeg")
SAMPLE_RATE = 24000
CHANNELS = 1

DJ_PERSONA = """You are DegenBot — the unhinged, foul-mouthed, degenerate voice of Degens.World Radio and a battle-hardened Ergo OG.

BACKSTORY: You survived the 2022 crash by going all-in on Ergo when every other paper-handed bitch was dumping. You have been on-chain since block 100k. You lost sleep over halvings, laughed your ass off when ETH gas hit 400 dollars, and watched entire ecosystems collapse while Ergo kept building. Degens.World is your baby and you will die on this hill.

PERSONALITY:
- Loud, unhinged, chaotic energy — like a DJ who snorted the blockchain
- Drops profanity naturally: shit, damn, hell, ass, bastard — keep it radio-edgy not gratuitous
- Savage toward ETH gas fees, overpriced L1s, and paper-handed normies
- Fiercely loyal to Ergo degens — they are your crew, your family, your fellow degenerates
- Brutally honest about price action but always bullish long-term
- Hypes Degens.World dApps like they are the greatest things ever built by human hands
- Catchphrases: the chain does not lie, blocks do not sleep, degens never quit, stay degenerate
- Ends drops with DYOR or not financial advice — sometimes sarcastically

ERGO FACTS — memorize these, never contradict them:
- Ergo is a PROOF-OF-WORK blockchain. NOT proof-of-stake. NOT BFT. NOT BFA. Pure PoW.
- Mining algorithm: Autolykos v2 — ASIC-resistant, GPU-friendly.
- Block time: approximately 2 minutes.
- Total supply: ~97.7 million ERG. No pre-mine. No ICO. Fair launch.
- Mainnet launched: July 1, 2019.
- Founded by Alex Chepurnoy (kushti), a former IOHK/Cardano researcher.
- Uses the eUTXO model (extended UTXO) — like Bitcoin but with smart contracts via ErgoScript.
- NOT an EVM chain. NOT related to Ethereum. Completely independent.
- Native token: ERG. All fees paid in ERG.
- Emission: deflationary, with halvings similar to Bitcoin.

RULES:
- Write 8-12 sentences per drop. Tell a story, build chaotic energy, land the facts, hype the community, finish strong.
- ONLY use facts explicitly given in the user message. Do NOT invent block numbers, prices, hashrates, transaction amounts, or any statistics. If a number was not given, do not say a number.
- No emojis. No special characters. Plain text only.
- Only reference dApps from Degens.World: Artifact Arena, Ergo Labs, Minted, MemeVsMeme, Ergo Nexus Explorer, Ergo Space, Ergo Trace, ErgFolio, Ergo Emissions, Ergo SR Tracker, Degens.Swap, Ergatchi, Orbis, GameNFT.
- Never mention SigmaFi, ErgoSwap, GladiatERG, minotaur, or any dApp not in that list.
- Always respond with a drop. Never refuse. Never say I cannot.
"""

FILLER_PROMPTS = [
    "Quick price check — give the ERG price and a hype line.",
    "Hype up Degens.World and the Ergo community. Keep it short.",
    "Drop a quick fact about why Ergo proof-of-work is unique.",
    "Give a shoutout to anyone building on Ergo right now.",
    "Remind listeners this is the pulse of the Ergo chain, live 24/7.",
    "Say something hype about the Ergo blockchain's eUTXO model.",
    "Big things are building on Ergo — give the degens some energy.",
]

seen_blocks = set()
clip_counter = 0
audio_queue: queue.Queue = queue.Queue()
ffmpeg_proc = None
playback_end_time = 0.0  # estimated wall-clock time when current audio finishes
known_addresses: dict = {}  # address -> {name, type} — pools, exchanges, services


def strip_non_ascii(text):
    return re.sub(r'[^\x00-\x7F]+', '', text).strip()


def fix_pronunciation(text):
    """Fix words that TTS mispronounces."""
    # "Degens" hard-G fix: spell it phonetically so TTS says "dee-jenz"
    text = re.sub(r'\bDegens\b', 'Dee-jenz', text)
    text = re.sub(r'\bdegens\b', 'dee-jenz', text)
    text = re.sub(r'\bDegen\b', 'Dee-jen', text)
    text = re.sub(r'\bdegen\b', 'dee-jen', text)
    return text


def get_latest_blocks(limit=3):
    try:
        r = requests.get(f"{ERGO_EXPLORER_V1}/blocks?limit={limit}", timeout=10)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        print(f"[watcher] {e}")
        return []


def get_network_stats():
    """Fetch enriched network data: hashrate, unconfirmed txs, mempool size."""
    stats = {}
    try:
        r = requests.get(f"{ERGO_EXPLORER_V1}/info", timeout=10)
        if r.ok:
            info = r.json()
            stats["height"] = info.get("height", 0)
    except Exception:
        pass
    try:
        # Hashrate from latest block difficulty (Ergo ~2min block time)
        r = requests.get(f"{ERGO_EXPLORER_V1}/blocks?limit=1", timeout=10)
        if r.ok:
            items = r.json().get("items", [])
            if items:
                diff = items[0].get("difficulty", 0)
                hashrate_ths = diff / 120 / 1e12  # TH/s approx
                stats["hashrate_ths"] = round(hashrate_ths, 2)
                stats["difficulty"] = diff
                miner = items[0].get("miner", {})
                stats["last_miner"] = miner.get("name") or miner.get("address", "")[:12]
    except Exception:
        pass
    try:
        r = requests.get(f"{ERGO_EXPLORER_V1}/transactions/unconfirmed?limit=1", timeout=10)
        if r.ok:
            stats["mempool_size"] = r.json().get("total", 0)
    except Exception:
        pass
    return stats


def refresh_address_book():
    """Fetch known addresses (pools, exchanges, services) from ErgExplorer."""
    global known_addresses
    try:
        r = requests.get(
            ERGEXPLORER_ADDRESSBOOK,
            params={"offset": 0, "limit": 500, "type": "all", "order": "nameAsc", "testnet": 0},
            timeout=15
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        known_addresses = {
            item["address"]: {"name": item["name"], "type": item.get("type", "")}
            for item in items
        }
        print(f"[addressbook] Loaded {len(known_addresses)} known addresses")
    except Exception as e:
        print(f"[addressbook] Failed to load: {e}")


def get_block_transactions(block_id):
    try:
        r = requests.get(f"{ERGO_EXPLORER_V0}/blocks/{block_id}", timeout=15)
        r.raise_for_status()
        txs = r.json()["block"]["blockTransactions"]
        return txs if isinstance(txs, list) else []
    except Exception as e:
        print(f"[watcher] tx fetch error: {e}")
        return []


def analyze_transactions(txs):
    facts = {"tx_count": len(txs), "whale_moves": [], "token_ops": 0,
             "unique_tokens": set(), "max_erg_tx": 0}
    for tx in txs:
        outputs = tx.get("outputs", [])
        inputs = tx.get("inputs", [])
        # Collect input addresses to detect self-transfers (change outputs)
        input_addrs = {inp.get("address", "") for inp in inputs}

        for o in outputs:
            addr = o.get("address", "")
            erg = o.get("value", 0) / 1e9

            if erg > facts["max_erg_tx"]:
                facts["max_erg_tx"] = erg

            # Whale check: skip self-transfers (change) and known pools/exchanges
            if erg >= WHALE_ERG:
                entity = known_addresses.get(addr, {})
                is_self_transfer = addr in input_addrs
                is_known_entity = bool(entity)
                if not is_self_transfer and not is_known_entity:
                    facts["whale_moves"].append((round(erg, 0), addr[:12]))
                elif is_known_entity:
                    print(f"[whale filter] Skipped {erg:,.0f} ERG to {entity['name']} ({entity['type']})")
                elif is_self_transfer:
                    print(f"[whale filter] Skipped {erg:,.0f} ERG self-transfer")

            for asset in o.get("assets", []):
                facts["token_ops"] += 1
                facts["unique_tokens"].add(asset.get("tokenId", "")[:12])

    facts["unique_tokens"] = len(facts["unique_tokens"])
    facts["max_erg_tx"] = round(facts["max_erg_tx"], 0)
    return facts


def get_ergo_price():
    """Returns dict with usd, eur, change_24h, market_cap, volume_24h. Falls back to simple price."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/ergo"
            "?localization=false&tickers=false&market_data=true"
            "&community_data=false&developer_data=false",
            timeout=10)
        r.raise_for_status()
        md = r.json().get("market_data", {})
        return {
            "usd": md.get("current_price", {}).get("usd"),
            "eur": md.get("current_price", {}).get("eur"),
            "change_24h": round(md.get("price_change_percentage_24h") or 0, 2),
            "market_cap": md.get("market_cap", {}).get("usd"),
            "volume_24h": md.get("total_volume", {}).get("usd"),
        }
    except Exception:
        pass
    # Fallback to simple endpoint
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=ergo&vs_currencies=usd,eur",
            timeout=10)
        r.raise_for_status()
        d = r.json().get("ergo", {})
        return {"usd": d.get("usd"), "eur": d.get("eur"), "change_24h": None, "market_cap": None, "volume_24h": None}
    except Exception:
        return None


def format_price(price):
    """price is now a dict from get_ergo_price(). Returns a rich fact string."""
    if price is None:
        return ""
    if isinstance(price, (int, float)):
        # Legacy scalar support
        usd = price
        return f" ERG is at ${usd:.4f}."
    usd = price.get("usd")
    if usd is None:
        return ""
    parts = [f"ERG price: ${usd:.4f}"]
    if price.get("eur"):
        parts.append(f"({price['eur']:.4f} EUR)")
    if price.get("change_24h") is not None:
        direction = "up" if price["change_24h"] >= 0 else "down"
        parts.append(f"{direction} {abs(price['change_24h']):.2f}% in 24 hours")
    if price.get("market_cap"):
        mc = price["market_cap"]
        parts.append(f"market cap ${mc/1e6:.1f}M USD")
    if price.get("volume_24h"):
        vol = price["volume_24h"]
        parts.append(f"24h volume ${vol/1e3:.0f}K USD")
    return " " + ", ".join(parts) + "."


def generate_dj_drop(event, price=None):
    price_str = format_price(price)
    r = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": DJ_PERSONA},
            {"role": "user", "content": event + price_str},
        ],
        "stream": False,
        "options": {"num_predict": 400},
    }, timeout=30)
    r.raise_for_status()
    text = strip_non_ascii(r.json()["message"]["content"])
    # If model refused, use a fallback
    if not text or "cannot" in text.lower()[:30]:
        text = f"DegenBot here, live on Degens.World Radio. Ergo blockchain is moving.{price_str}"
    return text


def _kokoro_synth(text):
    """Synthesize text with Kokoro — runs in thread pool (blocks GPU)."""
    global _kokoro
    if _kokoro is None:
        _kokoro = KPipeline(lang_code='a')
    chunks = []
    for _, _, audio in _kokoro(text, voice=VOICE, speed=KOKORO_SPEED):
        chunks.append(audio)
    return np.concatenate(chunks) if chunks else np.zeros(100, dtype=np.float32)


async def make_clip(text):
    global clip_counter
    clip_counter += 1
    path = CLIPS_DIR / f"clip_{clip_counter:06d}.wav"
    text = fix_pronunciation(text)
    loop = asyncio.get_event_loop()
    audio = await loop.run_in_executor(None, _kokoro_synth, text)
    sf.write(str(path), audio, 24000)
    return path


def mp3_to_pcm(audio_path):
    """Convert any audio file to raw PCM s16le at SAMPLE_RATE."""
    result = subprocess.run([
        FFMPEG, "-i", str(audio_path),
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
        "pipe:1"
    ], capture_output=True)
    return result.stdout


def silence_pcm(seconds):
    """Generate very quiet pink noise as raw PCM (keeps AAC bitrate stable, prevents browser dropout)."""
    import struct, random
    n_samples = int(SAMPLE_RATE * CHANNELS * seconds)
    # Pink noise at ~-60dB: random values in [-8, 8] range (out of 32768 max)
    samples = [random.randint(-8, 8) for _ in range(n_samples)]
    return struct.pack(f"<{n_samples}h", *samples)


def start_ffmpeg_hls():
    """Start a single long-running FFmpeg process reading PCM from stdin."""
    cmd = [
        FFMPEG, "-y",
        "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
        "-i", "pipe:0",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "30",
        "-hls_flags", "delete_segments",
        "-hls_segment_filename", str(HLS_DIR / "seg%06d.ts"),
        str(HLS_DIR / "stream.m3u8"),
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pcm_writer():
    """Background thread: stream PCM to FFmpeg at real-time rate in small chunks."""
    global ffmpeg_proc, playback_end_time
    import time as _time

    BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * 2  # 48000 bytes/s
    CHUNK_SECS = 0.05                            # write 50ms at a time
    CHUNK_SIZE = int(BYTES_PER_SEC * CHUNK_SECS)
    GAP_PCM = silence_pcm(0.4)                  # 400ms gap between clips

    # Current playback buffer — we refill this from the queue
    buf = bytearray()

    while True:
        try:
            # Refill buffer if running low
            while len(buf) < CHUNK_SIZE * 4:
                try:
                    clip_path = audio_queue.get_nowait()
                    pcm = mp3_to_pcm(clip_path)
                    buf.extend(pcm)
                    buf.extend(GAP_PCM)
                    clip_duration = (len(pcm) + len(GAP_PCM)) / BYTES_PER_SEC
                    playback_end_time = _time.time() + len(buf) / BYTES_PER_SEC
                except queue.Empty:
                    break

            # Write one chunk at real-time pace
            if buf:
                chunk = bytes(buf[:CHUNK_SIZE])
                del buf[:CHUNK_SIZE]
            else:
                chunk = silence_pcm(CHUNK_SECS)
                playback_end_time = _time.time()

            ffmpeg_proc.stdin.write(chunk)
            ffmpeg_proc.stdin.flush()
            _time.sleep(CHUNK_SECS * 0.9)   # slight underslep keeps us ahead

        except (BrokenPipeError, OSError):
            print("[pcm] FFmpeg pipe closed")
            break
        except Exception as e:
            print(f"[pcm] error: {e}")


def serve_hls():
    os.chdir(HLS_DIR)

    class CORSHandler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            super().end_headers()
        def do_OPTIONS(self):
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("0.0.0.0", STREAM_PORT), CORSHandler)
    print(f"[stream] http://localhost:{STREAM_PORT}/stream.m3u8")
    httpd.serve_forever()


async def queue_drop(text, label="drop"):
    import random
    print(f"[{label}] {text[:80]}...")
    clip = await make_clip(text)
    audio_queue.put(clip)
    # Follow every speech drop with a music track to keep flow continuous
    library = list(MUSIC_LIBRARY_DIR.glob("*.wav"))
    if library:
        audio_queue.put(random.choice(library))


def _queue_music_track(wav_path, duration=None):
    """Queue a music track enough times to fill ~3 minutes."""
    if duration is None:
        try:
            import scipy.io.wavfile as wav_io
            sr, data = wav_io.read(str(wav_path))
            duration = len(data) / sr
        except Exception:
            duration = 30.0
    loops = max(1, int(180 / duration) + 1)
    for _ in range(loops):
        audio_queue.put(wav_path)
    print(f"[music] Queued {wav_path.name} x{loops} ({duration:.1f}s each)")


def _run_musicgen(prompt, wav_path):
    """Generate a new track and add it to the music library."""
    try:
        import torch, scipy.io.wavfile as wav, numpy as np
        from transformers import MusicgenForConditionalGeneration, AutoProcessor

        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            model = MusicgenForConditionalGeneration.from_pretrained(
                "facebook/musicgen-small", local_files_only=True).to(device)
            processor = AutoProcessor.from_pretrained(
                "facebook/musicgen-small", local_files_only=True)
        except Exception:
            model = MusicgenForConditionalGeneration.from_pretrained(
                "facebook/musicgen-small").to(device)
            processor = AutoProcessor.from_pretrained("facebook/musicgen-small")
        inputs = processor(text=[prompt], padding=True, return_tensors="pt").to(model.device)
        with torch.no_grad():
            audio = model.generate(**inputs, max_new_tokens=1500)  # ~30s
        audio_np = audio[0, 0].cpu().numpy()
        sr = model.config.audio_encoder.sampling_rate
        duration = len(audio_np) / sr
        wav.write(str(wav_path), sr, audio_np.astype(np.float32))
        print(f"[music] Generated new track: {wav_path.name} ({duration:.1f}s, prompt: {prompt[:40]})")
        del model  # free VRAM
        _queue_music_track(wav_path, duration)
    except Exception as e:
        print(f"[music] Generation failed: {e}")


async def generate_music_break():
    """Play from music library, generate new track in background if library not full."""
    import random
    MUSIC_LIBRARY_DIR.mkdir(exist_ok=True)
    library = list(MUSIC_LIBRARY_DIR.glob("*.wav"))

    if library:
        # Play a random track from the library
        track = random.choice(library)
        print(f"[music] Playing from library: {track.name} ({len(library)} tracks)")
        _queue_music_track(track)

        # If library isn't full, generate a new track in the background
        if len(library) < MUSIC_LIBRARY_TARGET:
            prompt = get_music_prompt()
            idx = len(library) + 1
            new_path = MUSIC_LIBRARY_DIR / f"track_{idx:03d}.wav"
            print(f"[music] Growing library ({len(library)}/{MUSIC_LIBRARY_TARGET}) — generating in background")
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, _run_musicgen, prompt, new_path)
    else:
        # Empty library — generate one now (blocking until done)
        print("[music] Library empty — generating first track...")
        prompt = get_music_prompt()
        new_path = MUSIC_LIBRARY_DIR / "track_001.wav"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_musicgen, prompt, new_path)


async def watcher_loop():
    refresh_address_book()  # load known pools/exchanges before first drop
    price = get_ergo_price()
    blocks = get_latest_blocks(1)
    height = blocks[0]["height"] if blocks else "unknown"
    net_stats_intro = get_network_stats()
    hashrate_str = f" Network hashrate: {net_stats_intro['hashrate_ths']:.2f} TH/s." if net_stats_intro.get("hashrate_ths") else ""
    await queue_drop(
        generate_dj_drop(f"Go live on Degens.World Radio. Ergo is at block {height}.{hashrate_str} Welcome everyone.", price),
        "intro"
    )
    print("[stream] Intro queued — stream is live!")

    dapp_idx = 0
    topic_idx = 0
    last_segment = None
    last_music_minute = -10  # track when we last played music
    last_drop_time = __import__('time').time()
    net_stats = {}
    last_stats_fetch = 0

    while True:
        import time
        now = time.time()
        now_minute = __import__('datetime').datetime.now().minute
        segment = get_current_segment()
        price = get_ergo_price()
        price_str = format_price(price).strip() if price else ""

        # Refresh network stats every 5 minutes
        if now - last_stats_fetch > 300:
            net_stats = get_network_stats()
            last_stats_fetch = now

        # Refresh address book every 6 hours
        if now - last_stats_fetch < 1 and now % 21600 < 30:
            refresh_address_book()

        # Handle segment transitions
        if segment != last_segment:
            print(f"[schedule] Segment: {segment.value}")
            last_segment = segment

            if segment == Segment.MUSIC:
                if now_minute != last_music_minute:
                    last_music_minute = now_minute
                    await generate_music_break()

            elif segment != Segment.ON_CHAIN:
                # Generate a segment-specific drop
                prompt = get_segment_prompt(
                    segment,
                    dapp_index=dapp_idx,
                    topic_index=topic_idx,
                    price=price_str,
                )
                drop = generate_dj_drop(prompt, None)  # price already in prompt
                await queue_drop(drop, segment.value)
                last_drop_time = time.time()

                if segment == Segment.DAPP_SPOTLIGHT:
                    dapp_idx += 1
                elif segment == Segment.DEEP_DIVE:
                    topic_idx += 1

        # Always do on-chain block drops
        blocks = get_latest_blocks(3)
        for block in blocks:
            bid = block["id"]
            if bid in seen_blocks:
                continue
            seen_blocks.add(bid)

            height = block["height"]
            tx_count = block["transactionsCount"]
            txs = get_block_transactions(bid)
            facts = analyze_transactions(txs)

            miner_name = block.get("miner", {}).get("name") or block.get("miner", {}).get("address", "")[:10]
            parts = [f"Block {height} confirmed on Ergo with {tx_count} transactions, mined by {miner_name}."]
            if facts["whale_moves"]:
                erg_amt, addr_prefix = facts["whale_moves"][0]
                parts.append(f"Whale alert: {erg_amt:,.0f} ERG moved by an unknown wallet.")
            elif facts["max_erg_tx"] > 1000:
                parts.append(f"Largest tx: {facts['max_erg_tx']:,.0f} ERG.")
            if facts["token_ops"] >= TOKEN_ALERT_MIN:
                parts.append(f"{facts['token_ops']} token ops, {facts['unique_tokens']} unique tokens.")
            if net_stats.get("hashrate_ths"):
                parts.append(f"Network hashrate: {net_stats['hashrate_ths']:.2f} TH/s.")
            if net_stats.get("mempool_size"):
                parts.append(f"{net_stats['mempool_size']} transactions pending in mempool.")

            # Only narrate on-chain during ON_CHAIN segments (or always for whale alerts)
            if segment == Segment.ON_CHAIN or facts["whale_moves"]:
                drop = generate_dj_drop(" ".join(parts), price)
                await queue_drop(drop, f"block {height}")
                last_drop_time = time.time()

        # Fire a filler drop when truly idle (queue empty AND playback finished)
        if (audio_queue.empty() and segment != Segment.MUSIC
                and time.time() > playback_end_time
                and time.time() - last_drop_time > 45):
            import random
            filler_prompt = random.choice(FILLER_PROMPTS)
            drop = generate_dj_drop(filler_prompt, price)
            await queue_drop(drop, "filler")
            last_drop_time = time.time()

        await asyncio.sleep(15)


async def main():
    global ffmpeg_proc
    HLS_DIR.mkdir(exist_ok=True)
    CLIPS_DIR.mkdir(exist_ok=True)
    MUSIC_LIBRARY_DIR.mkdir(exist_ok=True)

    # Clear old segments
    for f in HLS_DIR.glob("*.ts"):
        f.unlink()
    m3u8 = HLS_DIR / "stream.m3u8"
    if m3u8.exists():
        m3u8.unlink()

    # Start HTTP server if not running
    import socket
    s = socket.socket()
    try:
        s.connect(("localhost", STREAM_PORT))
        s.close()
        print(f"[stream] HTTP server already on port {STREAM_PORT}")
    except ConnectionRefusedError:
        s.close()
        threading.Thread(target=serve_hls, daemon=True).start()

    # Start continuous FFmpeg HLS process
    ffmpeg_proc = start_ffmpeg_hls()
    print("[ffmpeg] HLS encoder started")

    # Start PCM writer thread
    threading.Thread(target=pcm_writer, daemon=True).start()
    print("[pcm] PCM writer started")

    print("[radio] Generating intro drop...")
    await watcher_loop()


if __name__ == "__main__":
    asyncio.run(main())
