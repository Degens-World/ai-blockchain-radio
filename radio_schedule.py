"""
Degens.World Radio — Segment Scheduler
Determines what type of content to generate based on time of day.
"""

from datetime import datetime
from enum import Enum


class Segment(Enum):
    TOP_OF_HOUR = "top_of_hour"
    MUSIC = "music"
    DAPP_SPOTLIGHT = "dapp_spotlight"
    ON_CHAIN = "on_chain"
    MARKET_VIBES = "market_vibes"
    ECOSYSTEM_REPORT = "ecosystem_report"
    COMMUNITY_CALLOUT = "community_callout"
    DEEP_DIVE = "deep_dive"
    MORNING_BRIEFING = "morning_briefing"
    MIDDAY_REPORT = "midday_report"
    AFTER_HOURS = "after_hours"
    LATE_NIGHT = "late_night"


# Repeating hour schedule — (start_minute, end_minute, segment)
HOUR_SCHEDULE = [
    (0,  2,  Segment.TOP_OF_HOUR),
    (2,  6,  Segment.MUSIC),
    (6,  8,  Segment.DAPP_SPOTLIGHT),
    (8,  20, Segment.ON_CHAIN),
    (20, 22, Segment.MARKET_VIBES),
    (22, 26, Segment.MUSIC),
    (26, 28, Segment.ECOSYSTEM_REPORT),
    (28, 40, Segment.ON_CHAIN),
    (40, 42, Segment.COMMUNITY_CALLOUT),
    (42, 46, Segment.MUSIC),
    (46, 49, Segment.DEEP_DIVE),
    (49, 60, Segment.ON_CHAIN),
]

# Special segments at specific hours (overrides hour schedule for first 5 min)
SPECIAL_HOURS = {
    9:  Segment.MORNING_BRIEFING,
    12: Segment.MIDDAY_REPORT,
    16: Segment.AFTER_HOURS,
    0:  Segment.LATE_NIGHT,
}

DAPP_LIST = [
    "Artifact Arena",
    "Ergo Labs",
    "Minted",
    "MemeVsMeme",
    "Ergo Nexus Explorer",
    "Ergo Space",
    "Ergo Trace",
    "ErgFolio",
    "Ergo Emissions",
    "Ergo SR Tracker",
    "Degens.Swap",
    "Ergatchi",
    "Orbis",
    "GameNFT",
]

DEEP_DIVE_TOPICS = [
    "Why Ergo's proof-of-work is different from Bitcoin and why it matters for long-term security",
    "The eUTXO model and why it makes Ergo smarter than account-based chains like Ethereum",
    "Ergo's emission schedule and what the halvings mean for miners and holders",
    "Why gas fee nightmares on Ethereum make Ergo's approach so compelling",
    "The story of Ergo surviving the 2022 crash while others collapsed",
    "What makes Ergo's smart contracts more powerful than people realize",
    "The Ergo community: who builds here and why they chose this chain",
    "Proof of work vs proof of stake — the honest breakdown",
]

MUSIC_PROMPTS = {
    "morning":    "uplifting lo-fi hip hop, morning energy, positive vibes, bright synths, no vocals",
    "midday":     "energetic electronic beats, crypto trading floor vibes, driving rhythm, no vocals",
    "afternoon":  "lofi hip hop beats, crypto vibes, dark atmospheric, steady groove, no vocals",
    "evening":    "deep house, chill electronic, smooth bass, crypto night vibes, no vocals",
    "late_night": "dark ambient electronic, moody synths, underground crypto vibes, slow tempo, no vocals",
    "default":    "lofi hip hop beats, crypto vibes, steady groove, chill atmosphere, no vocals",
}


def get_music_prompt():
    hour = datetime.now().hour
    if 6 <= hour < 10:
        return MUSIC_PROMPTS["morning"]
    elif 10 <= hour < 14:
        return MUSIC_PROMPTS["midday"]
    elif 14 <= hour < 18:
        return MUSIC_PROMPTS["afternoon"]
    elif 18 <= hour < 22:
        return MUSIC_PROMPTS["evening"]
    else:
        return MUSIC_PROMPTS["late_night"]


def get_current_segment() -> Segment:
    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # Special hour override for first 5 minutes
    if minute < 5 and hour in SPECIAL_HOURS:
        return SPECIAL_HOURS[hour]

    # Regular hour schedule
    for start, end, segment in HOUR_SCHEDULE:
        if start <= minute < end:
            return segment

    return Segment.ON_CHAIN


def get_segment_prompt(segment: Segment, dapp_index: int = 0,
                       topic_index: int = 0, block_data: str = "",
                       price: str = "") -> str:
    price_str = f" ERG is at {price}." if price else ""

    if segment == Segment.TOP_OF_HOUR:
        return (f"Top of the hour on Degens.World Radio. Give a sharp news-anchor style opener: "
                f"recap the last hour on Ergo, mention the current price{price_str}, "
                f"tease what is coming up in the next hour. Make it sound like a real radio station top-of-hour break.")

    if segment == Segment.DAPP_SPOTLIGHT:
        dapp = DAPP_LIST[dapp_index % len(DAPP_LIST)]
        return (f"dApp Spotlight segment. You are highlighting {dapp} from Degens.World. "
                f"Tell the listeners what it does, why degens love it, and why they should check it out. "
                f"Be enthusiastic but informative. 6-8 sentences.")

    if segment == Segment.MARKET_VIBES:
        return (f"Market Vibes segment. Give your honest take on ERG price action right now.{price_str} "
                f"Is it a good time to accumulate? What is the vibe in the market? "
                f"Reference the broader crypto market if relevant. Keep it real, not hype. DYOR.")

    if segment == Segment.ECOSYSTEM_REPORT:
        return (f"Ecosystem Report segment. Give listeners a quick rundown on what is happening "
                f"in the Ergo ecosystem right now. Talk about recent activity on Degens.World dApps, "
                f"on-chain stats, and any notable developments. Sound like a news reporter.")

    if segment == Segment.COMMUNITY_CALLOUT:
        return (f"Community Callout segment. Give a massive shoutout to the Ergo community, "
                f"the miners keeping the chain alive, the builders shipping dApps on Degens.World, "
                f"and the degens holding through thick and thin. Make people feel part of something bigger.")

    if segment == Segment.DEEP_DIVE:
        topic = DEEP_DIVE_TOPICS[topic_index % len(DEEP_DIVE_TOPICS)]
        return (f"Deep Dive segment. The topic is: {topic}. "
                f"Give a real, informative but entertaining breakdown. Teach the listeners something. "
                f"10-12 sentences. This is the educational segment of the show.")

    if segment == Segment.MORNING_BRIEFING:
        return (f"Good morning degens! It is the Morning Briefing on Degens.World Radio. "
                f"Give a full morning market recap: ERG overnight price action{price_str}, "
                f"what happened on-chain while people slept, and what to watch today. "
                f"Energetic morning energy. 8-10 sentences.")

    if segment == Segment.MIDDAY_REPORT:
        return (f"Midday Degen Report. You are halfway through the trading day. "
                f"Give a midday check-in: how is ERG doing{price_str}, what is the midday vibe, "
                f"anything popping on Degens.World dApps. Sound like a midday news anchor.")

    if segment == Segment.AFTER_HOURS:
        return (f"After Hours on Degens.World Radio. The market day is winding down but the chain never stops. "
                f"Give a relaxed, end-of-day recap. ERG price today{price_str}, winners and losers, "
                f"what to watch tonight. More chill, less hype. Like an evening radio show.")

    if segment == Segment.LATE_NIGHT:
        return (f"Late Night Degens. It is past midnight and only the real ones are still up. "
                f"Speak to the night owls, the insomniacs, the ones watching charts at 2am. "
                f"Dark, moody vibe, still energetic but more underground. ERG price check{price_str}. "
                f"This is for the degens who never sleep.")

    # Default ON_CHAIN
    return block_data if block_data else "Give a quick on-chain status update and keep the energy up."
