from typing import Dict, Tuple
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH") 
BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
DISTANCE_API_KEY = os.getenv("DISTANCE_API_KEY")
BOT_CHAT_ID = 974050175

UTM_COORDS = (1.56965, 103.63927)
MAX_RADIUS_KM = 30
EARTH_RADIUS_KM = 6371

GROUP_ID: Dict[int, str] = {
    -4289055354: "⚡️GoDrive🚖",
    -1001806905741: "🚨UTM TRANSPORTER🛻",
    -1002541339165: "PREBET UTM JB 🚖🅿️"
}

CUSTOM_LOCATIONS: Dict[str, Tuple[float, float] | Dict[str, str]] = {
    # KTDI
    "m23": (1.5655163,103.6346827),

    # K9 & K10
    "k10": (1.5607591,103.6488572),

    "cp": (1.5596179,103.6347324),

    "eco": (1.5437598,103.6302155),
    "alsafa": (1.5450333,103.6290217),
    "sri putri": (1.5444645,103.6569381),

    "aliases": {
        # KTDI
        "ma1a": "ma1", "ma1b": "ma1", "ma1c": "ma1",

        # KTF
        "h25a": "h25", "h25b": "h25", "h25c": "h25",

        # K10
        "kolej 10": "k10", "kolej10": "k10", "ub1": "k10", "ub2": "k10",

        # TAMAN UNIVERSITI
        "aeon": "aeon taman u",
        "familymart": "eco",
        "sds": "sds taman u",
        "al-safa": "alsafa", "alhayfa": "alsafa", "naseeb": "alsafa"
    }
}
