# ✅ GoDrive: Finalized Telegram UserBot & Bot Integration Script

from typing import Optional, Tuple, Dict
import json
import urllib.parse
import re
import aiohttp
import asyncio
from math import radians, sin, cos, sqrt, atan2
from telethon import TelegramClient, events
from telethon.tl.types import UpdateDeleteMessages
from config import *  # Assume this contains API_ID, API_HASH, BOT_TOKEN, GROUP_ID, etc.
from collections import defaultdict
import time
import logging
import sqlite3
import os
from datetime import datetime
import pickle

# ========== Globals ==========
session: Optional[aiohttp.ClientSession] = None

# Use more aggressive reconnect and timeout settings for Telethon and aiohttp
from telethon.sessions import StringSession

TELETHON_TIMEOUT = 20  # seconds
TELETHON_RETRIES = 9999
AIOHTTP_TIMEOUT = 30  # seconds

client = TelegramClient(
    "userbot_session",
    API_ID,
    API_HASH,
    timeout=TELETHON_TIMEOUT,
    connection_retries=TELETHON_RETRIES,
)

location_cache: Dict[str, Optional[Tuple[float, float]]] = {}
distance_cache: Dict[Tuple[Tuple[float, float], Tuple[float, float]], Tuple[float, float]] = {}
message_map: Dict[str, int] = {}  # keep message_map keyed by composite string "chat_id:message_id"
driver_location: Optional[Tuple[float, float]] = None
user_states = defaultdict(lambda: {'state': None, 'data': {}})
last_user_message_time = {}  # user_id: timestamp

# ========== Utils ==========
def extract_locations(text):
    from_match = re.search(r"From\s*:\s*(.*)", text, re.IGNORECASE)
    to_match = re.search(r"To\s*:\s*(.*)", text, re.IGNORECASE)
    if from_match and to_match:
        return from_match.group(1).strip(), to_match.group(1).strip()
    match = re.search(r"(.+?)\s*(?:to|-)+\s*(.+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, None

def haversine(coord1, coord2):
    lat1, lon1 = map(radians, coord1)
    lat2, lon2 = map(radians, coord2)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return 6371 * 2 * atan2(sqrt(a), sqrt(1-a))

# Optimize safe_http_request for lower latency
async def safe_http_request(method, url, **kwargs):
    """
    Improved HTTP helper:
      - returns parsed body on 4xx (don't retry forever on Bad Request)
      - retries on network/5xx
      - logs response body for diagnostics
    """
    delay = 0.2
    max_delay = 2
    for attempt in range(3):
        try:
            async with session.request(method.upper(), url, **kwargs) as resp:
                text = await resp.text()
                ctype = resp.headers.get("Content-Type", "")
                # try to parse JSON if possible
                try:
                    data = await resp.json() if "application/json" in ctype else json.loads(text)
                except Exception:
                    data = {"_raw": text}
                # If client or server error:
                if 400 <= resp.status < 500:
                    # Log the body so you can see Telegram's "description"
                    logging.warning(f"HTTP {method.upper()} {url} returned {resp.status}: {text}")
                    return data
                if resp.status >= 500:
                    # server error -> raise to trigger retry
                    logging.warning(f"HTTP {method.upper()} {url} returned {resp.status}, retrying...")
                    raise aiohttp.ClientResponseError(
                        status=resp.status, request_info=resp.request_info, history=resp.history
                    )
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logging.warning(f"HTTP {method.upper()} {url} failed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
    raise Exception(f"HTTP {method.upper()} {url} failed after retries.")

async def get_coordinates(place: str) -> Optional[Tuple[float, float]]:
    if not place:
        return None
    place = place.lower().strip().split(',')[0]
    if place in location_cache:
        return location_cache[place]
    place = CUSTOM_LOCATIONS.get("aliases", {}).get(place, place)
    if place in CUSTOM_LOCATIONS:
        location_cache[place] = CUSTOM_LOCATIONS[place]
        return CUSTOM_LOCATIONS[place]
    for suffix in ["", " UTM Johor", " Johor Bahru"]:
        params = {"address": place + suffix, "key": GOOGLE_MAPS_API_KEY}
        try:
            data = await safe_http_request("get", "https://maps.googleapis.com/maps/api/geocode/json", params=params, timeout=3)
            if data.get("status") == "OK":
                loc = data["results"][0]["geometry"]["location"]
                coord = (loc["lat"], loc["lng"])
                if haversine(UTM_COORDS, coord) <= MAX_RADIUS_KM:
                    location_cache[place] = coord
                    return coord
        except Exception as e:
            continue
    return None

async def get_travel_data(origin, destination):
    key = (origin, destination)
    if key in distance_cache:
        return distance_cache[key]
    params = {
        "units": "metric",
        "origins": f"{origin[0]},{origin[1]}",
        "destinations": f"{destination[0]},{destination[1]}",
        "mode": "driving",
        "key": DISTANCE_API_KEY
    }
    try:
        data = await safe_http_request("get", "https://maps.googleapis.com/maps/api/distancematrix/json", params=params, timeout=3)
        if data["status"] == "OK":
            e = data["rows"][0]["elements"][0]
            if e["status"] == "OK":
                distance, duration = e["distance"]["value"] / 1000, e["duration"]["value"] // 60
                distance_cache[key] = (distance, duration)
                return distance, duration
    except Exception:
        pass
    return None, None

async def send_bot_message(text, reply_to=None, buttons=None):
    """
    Send using Bot API (no parse_mode) — avoid Markdown 400s.
    Keep payload minimal and log failures via safe_http_request.
    """
    payload = {
        "chat_id": BOT_CHAT_ID,
        "text": text,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return await safe_http_request("post", f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)

async def edit_bot_message(message_id: int, text: str, buttons=None):
    """Edit an existing bot message (Bot API) without parse_mode to avoid 400s."""
    payload = {
        "chat_id": BOT_CHAT_ID,
        "message_id": message_id,
        "text": text,
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    return await safe_http_request("post", url, json=payload)

def resolve_group_name(chat_id, chat_title=None):
    """
    Robustly resolve a group name from GROUP_ID mapping.
    Handles both raw IDs and Telegram channel IDs that include the -100 prefix.
    Falls back to chat_title or stringified id if no mapping found.
    """
    try:
        # direct match
        if chat_id in GROUP_ID:
            return GROUP_ID[chat_id]

        # try as string and handle -100 prefix -> convert '-1001234' -> '-1234'
        s = str(chat_id)
        if s.startswith('-100'):
            alt = int('-' + s[4:])
            if alt in GROUP_ID:
                return GROUP_ID[alt]

        # sometimes stored keys may be positive; try abs-match by digits
        digits = s.lstrip('-')
        for k in GROUP_ID.keys():
            if str(k).lstrip('-') == digits:
                return GROUP_ID[k]

    except Exception as e:
        print(f"⚠️ resolve_group_name error: {e}")

    # fallback to chat_title if available, else use id string
    if chat_title:
        return chat_title
    return f"Chat {chat_id}"

# Optimize gather_message_data to use resolve_group_name
async def gather_message_data(event) -> dict:
    """Gather ALL possible data from the message and sender"""
    sender = await event.get_sender()
    chat = await event.get_chat()

    # determine group name robustly
    raw_chat_id = event.chat_id
    chat_title = getattr(chat, 'title', None)
    group_name = resolve_group_name(raw_chat_id, chat_title)

    data = {
        # Sender Info
        "sender_id": sender.id,
        "sender_username": getattr(sender, 'username', None),
        "sender_first_name": getattr(sender, 'first_name', ''),
        "sender_last_name": getattr(sender, 'last_name', ''),
        "sender_phone": getattr(sender, 'phone', None),

        # Message Info
        "message_id": event.message.id,
        "message_text": event.message.text,
        "reply_to_msg_id": event.message.reply_to_msg_id,
        "message_date": event.message.date.strftime("%Y-%m-%d %H:%M:%S"),

        # Chat Info
        "chat_id": raw_chat_id,
        "chat_title": chat_title,
        "group_name": group_name,

        # Locations (if any)
        "pickup": None,
        "dropoff": None,
    }

    # Extract locations
    pickup, dropoff = extract_locations(data["message_text"])
    data.update({
        "pickup": pickup,
        "dropoff": dropoff
    })

    # Helpful debug log if group mapping wasn't from GROUP_ID (optional)
    if raw_chat_id not in GROUP_ID:
        print(f"ℹ️ Received message from unknown chat id {raw_chat_id} -> using '{group_name}'")

    return data

def get_db_conn():
    """Return a sqlite3 connection configured for WAL and a busy timeout."""
    db_file = os.path.join(os.path.dirname(__file__), "godrive.db")
    conn = sqlite3.connect(db_file, timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    return conn

def init_database():
    """Initialize SQLite database for messages (tg_message_id stored as TEXT, includes chat_id)."""
    try:
        db_file = os.path.join(os.path.dirname(__file__), "godrive.db")
        conn = get_db_conn()
        c = conn.cursor()
        # store tg_message_id as TEXT (composite key chat_id:message_id) and include chat_id
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            tg_message_id TEXT UNIQUE,
            chat_id INTEGER,
            sender_id INTEGER,
            sender_name TEXT,
            sender_username TEXT,
            sender_phone TEXT,
            group_name TEXT,
            message_text TEXT,
            reply_to_msg_id INTEGER,
            pickup TEXT,
            dropoff TEXT,
            contact_url TEXT,
            avatar_url TEXT,
            created_at TIMESTAMP,
            edited_at TIMESTAMP,
            is_deleted BOOLEAN DEFAULT 0
        )''')
        conn.commit()
        conn.close()
        print("✅ Database initialized")
    except Exception as e:
        print(f"❌ Database init failed: {e}")

async def ensure_avatar(sender_id):
    """Download user's profile photo to pwa/avatars/{sender_id}.jpg and return relative url or None"""
    try:
        avatars_dir = os.path.join(os.path.dirname(__file__), "pwa", "avatars")
        os.makedirs(avatars_dir, exist_ok=True)
        out_path = os.path.join(avatars_dir, f"{sender_id}.jpg")
        # If already exists, reuse
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return f"/avatars/{sender_id}.jpg"
        # get entity and download
        try:
            entity = await client.get_entity(sender_id)
            await client.download_profile_photo(entity, file=out_path)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return f"/avatars/{sender_id}.jpg"
        except Exception:
            # fallback: no photo or download failed
            return None
    except Exception as e:
        print(f"❌ ensure_avatar error: {e}")
    return None

def save_message_to_db(data: dict):
    """Save message to SQLite database (uses composite tg_message_id = 'chat_id:message_id')."""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        
        # Safely build sender_name from first/last (avoid literal "None")
        first = (data.get("sender_first_name") or "").strip()
        last = (data.get("sender_last_name") or "").strip()
        sender_name = (first + (" " + last if last else "")).strip() or None

        # contact_url
        if data.get("sender_username"):
            contact_url = f"https://t.me/{data['sender_username']}"
        else:
            contact_url = f"tg://user?id={data['sender_id']}"

        avatar_url = data.get("avatar_url")  # may be None

        # composite id (chat scoped) to avoid cross-chat ambiguity
        tg_key = f"{data.get('chat_id')}:{data.get('message_id')}"

        c.execute('''
            INSERT OR REPLACE INTO messages 
            (tg_message_id, chat_id, sender_id, sender_name, sender_username, sender_phone, 
             group_name, message_text, reply_to_msg_id, pickup, dropoff, contact_url, avatar_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tg_key,
            data.get("chat_id"),
            data["sender_id"],
            sender_name,
            data.get("sender_username"),
            data.get("sender_phone"),
            data.get("group_name"),
            data.get("message_text"),
            data.get("reply_to_msg_id"),
            data.get("pickup"),
            data.get("dropoff"),
            contact_url,
            avatar_url,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()
        print(f"✅ Message {tg_key} saved to database")
        return True
    except Exception as e:
        print(f"❌ Error saving to DB: {str(e)}")
        return False

# ========== Handlers ========== 
# Use fire-and-forget for heavy processing to keep event loop free
@client.on(events.NewMessage(chats=list(GROUP_ID.keys())))
async def new_message_handler(event):
    global driver_location, tracking_message_id
    # Handle location updates instantly
    if event.message.media and hasattr(event.message.media, 'geo'):
        driver_location = (event.message.media.geo.lat, event.message.media.geo.long)
        tracking_message_id = event.message.id
        print(f"📍 Location updated: {driver_location}")
        return
    # Schedule heavy processing in background
    asyncio.create_task(process_new_message(event))

async def process_new_message(event):
    try:
        data = await gather_message_data(event)
        full_name = data['sender_first_name']
        if data['sender_last_name']:
            full_name += f" {data['sender_last_name']}"
        full_name = full_name.strip()
        if not full_name:
            full_name = f"User {data['sender_id']}"
        
        # ✅ Attempt to fetch and save avatar (non-blocking-ish)
        try:
            avatar = await ensure_avatar(data["sender_id"])
            if avatar:
                data["avatar_url"] = avatar
        except Exception:
            data["avatar_url"] = None

        # ✅ Save to database for PWA to display (stores composite key)
        save_message_to_db(data)
        
        # prepare reply mapping keys as composite strings
        reply_key = f"{data.get('chat_id')}:{data.get('reply_to_msg_id')}" if data.get('reply_to_msg_id') else None

        # ✅ Keep legacy bot message sending (optional, can remove later)
        if not data["pickup"] and not data["dropoff"]:
            text = f"{full_name} | {data['group_name']}\n\n{data['message_text']}"
            reply_to_id = message_map.get(reply_key) if reply_key else None
            res = await send_bot_message(text, reply_to_id)
        else:
            info = f"{full_name} | {data['group_name']}\n\n{data['message_text']}"
            msg_text = data['message_text'] or ""
            cleaned_msg = re.sub(r"looking for driver", "", msg_text, flags=re.IGNORECASE).strip()
            prefill_msg = (
                "Hai. Dah ada driver ke?\n\n"
                f"{cleaned_msg}\n\n"
                "~ RM"
            )
            encoded_msg = urllib.parse.quote(prefill_msg)
            buttons = []
            if data["sender_username"]:
                buttons.append([{"text": "📩 Contact", "url": f"https://t.me/{data['sender_username']}?text={encoded_msg}"}])
                text = f"🚕 {info}"
            else:
                share_url = f"https://t.me/share/url?url={urllib.parse.quote(prefill_msg)}"
                text = f"🚗 {info}\n\n📤 Contact tg://user?id={data['sender_id']}"
                buttons.append([{"text": "🔗 Copy Message", "url": share_url}])
            reply_to_id = message_map.get(reply_key) if reply_key else None
            res = await send_bot_message(text, reply_to_id, buttons) if 'buttons' in locals() else await send_bot_message(text, reply_to_id)

        if "result" in res:
            key = f"{data.get('chat_id')}:{data.get('message_id')}"
            message_map[key] = res["result"]["message_id"]
            print("✅ Message processed successfully")
        else:
            print(f"⚠️ Legacy bot message failed: {res}")
    except Exception as e:
        print(f"❌ Error processing message: {str(e)}")
        fallback_text = f"New message in {resolve_group_name(event.chat_id)}\n\n{event.message.text}"
        await send_bot_message(fallback_text)

# Optimize edit handler for instant response
@client.on(events.MessageEdited(chats=list(GROUP_ID.keys())))
async def handle_edit(event):
    # Trigger edit processing if we have a composite mapping for this chat+msg id
    key = f"{event.chat_id}:{event.message.id}"
    if key in message_map or event.message.id in message_map:
        asyncio.create_task(process_edit_message(event))

async def process_edit_message(event):
    try:
        data = await gather_message_data(event)
        # Update DB using composite key (and fallback to numeric-only)
        try:
            conn = get_db_conn()
            c = conn.cursor()
            key = f"{data.get('chat_id')}:{data.get('message_id')}"
            # update by composite key; also try numeric legacy id for older rows
            c.execute('''
                UPDATE messages 
                SET message_text = ?, pickup = ?, dropoff = ?, edited_at = ? 
                WHERE tg_message_id = ? OR tg_message_id LIKE ?
            ''', (data["message_text"], data["pickup"], data["dropoff"], datetime.now().isoformat(), key, f'%:{data["message_id"]}'))
            conn.commit()
            conn.close()
            print(f"✅ Message {key} updated in database")
        except Exception as e:
            print(f"❌ Error updating DB: {str(e)}")
        
        # Legacy bot edit handling: lookup bot message id by composite (fallback to numeric)
        bot_message_id = message_map.get(f"{event.chat_id}:{event.message.id}") or message_map.get(str(event.message.id))
        if bot_message_id:
            full_name = data['sender_first_name']
            if data['sender_last_name']:
                full_name += f" {data['sender_last_name']}"
            full_name = full_name.strip()
            if not full_name:
                full_name = f"User {data['sender_id']}"
            if not data["pickup"] and not data["dropoff"]:
                text = f"{full_name} | {data['group_name']}\n\n{data['message_text']}"
                await edit_bot_message(bot_message_id, text)
            else:
                info = f"{full_name} | {data['group_name']}\n\n{data['message_text']}"
                msg_text = data['message_text'] or ""
                cleaned_msg = re.sub(r"looking for driver", "", msg_text, flags=re.IGNORECASE).strip()
                prefill_msg = (
                    "Hai. Dah ada driver ke?\n\n"
                    f"{cleaned_msg}\n\n"
                    "~ RM"
                )
                encoded_msg = urllib.parse.quote(prefill_msg)
                buttons = []
                if data["sender_username"]:
                    buttons.append([{"text": "📩 Contact", "url": f"https://t.me/{data['sender_username']}?text={encoded_msg}"}])
                    text = f"🚕 {info}"
                else:
                    share_url = f"https://t.me/share/url?url={urllib.parse.quote(prefill_msg)}"
                    text = f"🚗 {info}\n\nCopy then Contact tg://user?id={data['sender_id']}"
                    buttons.append([{"text": "📤 Copy Link Message", "url": share_url}])
                await edit_bot_message(bot_message_id, text, buttons if 'buttons' in locals() else None)
    except Exception as e:
        print(f"❌ Error editing message: {str(e)}")

@client.on(events.Raw)
async def handle_deleted_messages(event):
    if isinstance(event, UpdateDeleteMessages):
        for msg_id in event.messages:
            try:
                conn = get_db_conn()
                c = conn.cursor()
                # Mark as deleted: match exact composite or legacy numeric suffix
                c.execute('UPDATE messages SET is_deleted = 1 WHERE tg_message_id = ? OR tg_message_id LIKE ?', (str(msg_id), f'%:{msg_id}'))
                conn.commit()
                conn.close()
                print(f"🗑️ Message {msg_id} marked as deleted in DB")
            except Exception as e:
                print(f"❌ Error marking message as deleted: {e}")

            # Find bot message id by numeric key or any composite key that ends with :<msg_id>
            bot_msg_id = None
            try:
                for k, v in message_map.items():
                    if k == str(msg_id) or k.endswith(f":{msg_id}"):
                        bot_msg_id = v
                        break
            except Exception as e:
                print(f"⚠️ Error searching message_map for deleted msg {msg_id}: {e}")

            if bot_msg_id:
                try:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                    payload = {
                        "chat_id": BOT_CHAT_ID,
                        "message_id": bot_msg_id
                    }
                    # fire-and-forget deletion via safe_http_request
                    asyncio.create_task(safe_http_request("post", url, json=payload))
                    print(f"🗑️ Requested bot to delete message id {bot_msg_id}")
                except Exception as e:
                    print(f"❌ Failed to request bot delete for message {bot_msg_id}: {e}")

# ========== Bootstrap ==========

async def run():
    # Initialize database FIRST
    init_database()
    
    global session
    timeout = aiohttp.ClientTimeout(total=AIOHTTP_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=200, limit_per_host=50, ttl_dns_cache=300)
    session = aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False)
    
    # Warm caches from disk if present
    try:
        cache_file = os.path.join(os.path.dirname(__file__), "gd_cache.pkl")
        if os.path.exists(cache_file):
            with open(cache_file, "rb") as f:
                saved = pickle.load(f)
                location_cache.update(saved.get("location_cache", {}))
                distance_cache.update(saved.get("distance_cache", {}))
    except Exception:
        pass

    async def persist_caches_periodically():
        import os, pickle
        cache_file = os.path.join(os.path.dirname(__file__), "gd_cache.pkl")
        while True:
            try:
                with open(cache_file + ".tmp", "wb") as f:
                    pickle.dump({"location_cache": location_cache, "distance_cache": distance_cache}, f)
                os.replace(cache_file + ".tmp", cache_file)
            except Exception:
                pass
            await asyncio.sleep(30)

    asyncio.create_task(persist_caches_periodically())

    while True:
        try:
            # ensure session alive
            if session is None or session.closed:
                session = aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False)
            await client.start()
            await client.run_until_disconnected()
        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            logging.warning(f"Telegram connection lost: {e}. Reconnecting soon...")
            await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            await asyncio.sleep(2)
        finally:
            try:
                if session and not session.closed:
                    await session.close()
            except Exception:
                pass
            session = None

print("🚀 GoDrive is Running... Have Fun!")
client.loop.run_until_complete(run())