from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime
import json

app = Flask(__name__, static_folder='pwa', static_url_path='')
CORS(app)

DB_FILE = os.path.join(os.path.dirname(__file__), "godrive.db")

def init_db():
    """Initialize SQLite database for messages and history"""
    try:
        if not os.path.exists(DB_FILE):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            # messages table (existing) ...
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
            # new: history table
            c.execute('''CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY,
                tg_message_id TEXT,
                chat_id INTEGER,
                sender_id INTEGER,
                sender_name TEXT,
                contact_url TEXT,
                message_text TEXT,
                contacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.commit()
            conn.close()
            print("✅ Database created")
        else:
            # existing migration logic...
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            # ensure history table exists
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='history'")
            if not c.fetchone():
                print("🔧 Creating history table")
                c.execute('''CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY,
                    tg_message_id TEXT,
                    chat_id INTEGER,
                    sender_id INTEGER,
                    sender_name TEXT,
                    contact_url TEXT,
                    message_text TEXT,
                    contacted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
                conn.commit()
            # existing column checks...
            c.execute("PRAGMA table_info(messages)")
            cols = [r[1] for r in c.fetchall()]
            if 'reply_to_msg_id' not in cols:
                c.execute("ALTER TABLE messages ADD COLUMN reply_to_msg_id INTEGER")
                conn.commit()
            if 'avatar_url' not in cols:
                c.execute("ALTER TABLE messages ADD COLUMN avatar_url TEXT")
                conn.commit()
            if 'chat_id' not in cols:
                c.execute("ALTER TABLE messages ADD COLUMN chat_id INTEGER")
                conn.commit()
            conn.close()
    except Exception as e:
        print(f"❌ Database init error: {e}")

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_FILE)
    # enable WAL and sensible busy timeout to reduce contention
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    """Serve PWA index"""
    response = send_from_directory('pwa', 'index.html')
    # prevent aggressive caching during development / debugging
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

@app.route('/api/messages', methods=['GET'])
def get_messages():
    """Get all active messages, newest first"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT * FROM messages 
            WHERE is_deleted = 0 
            ORDER BY created_at DESC 
            LIMIT 100
        ''')
        rows = c.fetchall()
        conn.close()
        
        messages = [dict(row) for row in rows]
        print(f"📦 Fetched {len(messages)} active messages")
        
        # Prevent caching - always get fresh data
        response = jsonify({"status": "ok", "messages": messages})
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response
    except Exception as e:
        print(f"❌ Error fetching messages: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/messages/<tg_msg_id>', methods=['GET'])
def get_message(tg_msg_id):
    """Get specific message by Telegram ID (string-friendly)"""
    try:
        conn = get_db()
        c = conn.cursor()
        # try exact composite id first; also accept legacy numeric-only matches (suffix)
        c.execute('SELECT * FROM messages WHERE tg_message_id = ? OR tg_message_id LIKE ? OR tg_message_id = ?', 
                  (tg_msg_id, f'%:{tg_msg_id}', str(tg_msg_id)))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return jsonify({"status": "error", "message": "Not found"}), 404
        
        return jsonify({"status": "ok", "message": dict(row)})
    except Exception as e:
        print(f"❌ Error fetching message {tg_msg_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/messages/<tg_msg_id>', methods=['DELETE'])
def delete_message(tg_msg_id):
    """Soft delete message"""
    try:
        conn = get_db()
        c = conn.cursor()
        # accept composite id or legacy numeric id
        c.execute('UPDATE messages SET is_deleted = 1 WHERE tg_message_id = ? OR tg_message_id LIKE ?', (tg_msg_id, f'%:{tg_msg_id}'))
        conn.commit()
        conn.close()
        print(f"🗑️ Message {tg_msg_id} deleted")
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"❌ Error deleting message: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/messages', methods=['DELETE'])
def delete_all_messages():
    """Soft delete all active messages"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE messages SET is_deleted = 1 WHERE is_deleted = 0')
        deleted = c.rowcount or 0
        conn.commit()
        conn.close()
        print(f"🗑️ Cleared all active messages: {deleted}")
        return jsonify({"status": "ok", "deleted": deleted})
    except Exception as e:
        print(f"❌ Error clearing all messages: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/messages/<tg_msg_id>', methods=['PUT'])
def update_message(tg_msg_id):
    """Update message (for edits)"""
    try:
        data = request.get_json()
        conn = get_db()
        c = conn.cursor()
        # update by composite or legacy id
        c.execute('''
            UPDATE messages 
            SET message_text = ?, pickup = ?, dropoff = ?, edited_at = ? 
            WHERE tg_message_id = ? OR tg_message_id = ?
        ''', (data.get('message_text'), data.get('pickup'), data.get('dropoff'), datetime.now().isoformat(), tg_msg_id, str(data.get('message_id'))))
        conn.commit()
        conn.close()
        print(f"✏️ Message {tg_msg_id} updated")
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"❌ Error updating message: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard stats"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) as total FROM messages WHERE is_deleted = 0')
        total = c.fetchone()['total']
        
        c.execute('''
            SELECT COUNT(*) as today FROM messages 
            WHERE is_deleted = 0 AND DATE(created_at) = DATE('now')
        ''')
        today = c.fetchone()['today']
        
        conn.close()
        response = jsonify({"status": "ok", "total": total, "today": today})
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response
    except Exception as e:
        print(f"❌ Error fetching stats: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/copy', methods=['POST'])
def log_copy():
    """Log when users copy messages"""
    try:
        data = request.get_json()
        message = data.get('message', '')
        print(f"📋 User copied message: {message[:50]}...")
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Copy log error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/avatars/<path:filename>')
def serve_avatar(filename):
    avatars_dir = os.path.join(os.path.dirname(__file__), "pwa", "avatars")
    response = send_from_directory(avatars_dir, filename)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/api/history', methods=['GET'])
def get_history():
    """Return contact history (newest first)"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM history ORDER BY contacted_at DESC LIMIT 1000')
        rows = c.fetchall()
        conn.close()
        history = [dict(r) for r in rows]
        return jsonify({"status": "ok", "history": history})
    except Exception as e:
        print(f"❌ Error fetching history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/history', methods=['POST'])
def add_history():
    """Add a history record when user clicks Contact"""
    try:
        data = request.get_json() or {}
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO history (tg_message_id, chat_id, sender_id, sender_name, contact_url, message_text, contacted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('tg_message_id'),
            data.get('chat_id'),
            data.get('sender_id'),
            data.get('sender_name'),
            data.get('contact_url'),
            data.get('message_text'),
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"❌ Error adding history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/history/<int:hid>', methods=['DELETE'])
def delete_history_item(hid):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM history WHERE id = ?', (hid,))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"❌ Error deleting history {hid}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    init_db()
    print("🚀 Flask server starting on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
