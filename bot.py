import logging
import json
import os
import random
import sqlite3
import html
from datetime import datetime, date, timezone, timedelta
try:
    from ftfy import fix_text as _ftfy_fix
except ImportError:
    _ftfy_fix = None


def fix_mojibake(s):
    if not s or not isinstance(s, str):
        return s
    if _ftfy_fix:
        try:
            return _ftfy_fix(s)
        except Exception:
            pass
    try:
        return s.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s

TASHKENT_TZ = timezone(timedelta(hours=5))

def now_tash():
    return datetime.now(TASHKENT_TZ)

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'users.db')
QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), 'quiz_data.json')
IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'images')
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "").rstrip("/")
IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.webp']

ADMIN_ID = 5757696133
USTOZ_ID = 5757696133
ADMIN_USERNAME = "AliyevO"
CARD_NUMBER = "9860 0803 7979 5091"
CARD_HOLDER = "Q*****,O*****"
PRICE_UZS = 15000


def find_local_image(name):
    if not name:
        return None
    for ext in IMAGE_EXTS:
        p = os.path.join(IMAGES_DIR, f"{name}{ext}")
        if os.path.exists(p):
            return p
    return None


def get_image_url(name):
    if not name or not IMAGE_BASE_URL:
        return None
    return f"{IMAGE_BASE_URL}/{name}.png"


def esc(text):
    return html.escape(str(text) if text is not None else "")


KEYWORDS = [
    "darhol", "zudlik bilan", "shoshilinch", "tezlik bilan",
    "to'xtatish", "tohtatish", "to'xtab",
    "avariya yorug'lik ishorasi", "avariya signali", "avariya belgisi",
    "tibbiy yordam", "birinchi yordam", "1-tibbiy yordam",
    "ogohlantirish", "ogohlantiruvchi belgi",
    "yong'inni o'chirish", "o't o'chirgich",
    "politsiya", "GAI", "tez yordam", "103", "102", "101",
    "qutqaruv", "evakuatsiya",
    "taqiqlanadi", "ruxsat etiladi", "ruxsat berilmaydi", "majbur",
    "shart", "kerak", "mumkin emas",
    "yorug'lik signali", "tovush signali", "ovoz signali",
    "yo'l harakati qoidalari", "YHQ",
    "chap", "o'ng", "to'g'ri", "orqaga",
    "asosiy yo'l", "ikkinchi darajali yo'l",
    "piyodalar o'tish joyi", "piyoda",
    "svetofor", "yo'l belgisi", "razmetka",
    "tezlikni kamaytirish", "tezlikni oshirmaslik",
    "xavfsiz masofa", "xavfli",
]
KEYWORDS_SORTED = sorted(set(KEYWORDS), key=len, reverse=True)


def highlight_keywords(text):
    if not text:
        return text
    out = esc(text)
    import re
    for kw in KEYWORDS_SORTED:
        kw_esc = esc(kw)
        pattern = re.compile(re.escape(kw_esc), re.IGNORECASE)
        out = pattern.sub(lambda m: f"<b><u>{m.group(0)}</u></b>", out)
    return out


# ============== DATABASE ==============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            score INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 0,
            correct_answers INTEGER DEFAULT 0,
            wrong_categories TEXT DEFAULT '{}',
            streak INTEGER DEFAULT 0,
            best_streak INTEGER DEFAULT 0,
            last_active TEXT DEFAULT '',
            daily_streak INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_pro INTEGER DEFAULT 0,
            is_paid INTEGER DEFAULT 0,
            payment_status TEXT DEFAULT 'none'
        )
    ''')
    for col, definition in [
        ('first_name', 'TEXT'),
        ('streak', 'INTEGER DEFAULT 0'),
        ('best_streak', 'INTEGER DEFAULT 0'),
        ('last_active', "TEXT DEFAULT ''"),
        ('daily_streak', 'INTEGER DEFAULT 0'),
        ('is_paid', 'INTEGER DEFAULT 0'),
        ('payment_status', "TEXT DEFAULT 'none'"),
        ('referrer_id', 'INTEGER DEFAULT 0'),
        ('bonus_balance', 'INTEGER DEFAULT 0'),
        ('total_bonus_earned', 'INTEGER DEFAULT 0'),
        ('invited_count', 'INTEGER DEFAULT 0'),
        ('bonus_credited', 'INTEGER DEFAULT 0'),
    ]:
        try:
            c.execute(f'ALTER TABLE users ADD COLUMN {col} {definition}')
        except sqlite3.OperationalError:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS bookmarks (
            user_id INTEGER,
            question_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, question_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            added_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()


def lessons_visible():
    return get_setting('lessons_visible', '1') == '1'


def referral_visible():
    return get_setting('referral_visible', '1') == '1'


def get_pending_payments():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, first_name FROM users "
        "WHERE payment_status = 'pending' AND is_paid = 0 ORDER BY user_id DESC"
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_user_stats(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d['wrong_categories'] = json.loads(d.get('wrong_categories') or '{}')
    except Exception:
        d['wrong_categories'] = {}
    return d


def create_or_update_user(user_id, username, first_name, referrer_id=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id, referrer_id FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    is_new_user = row is None
    if not is_new_user:
        c.execute('UPDATE users SET username = ?, first_name = ? WHERE user_id = ?',
                  (username, first_name, user_id))
    else:
        valid_ref = 0
        if referrer_id and referrer_id != user_id and referrer_id != ADMIN_ID:
            c.execute('SELECT 1 FROM users WHERE user_id = ?', (referrer_id,))
            if c.fetchone():
                valid_ref = referrer_id
        c.execute(
            'INSERT INTO users (user_id, username, first_name, referrer_id) VALUES (?, ?, ?, ?)',
            (user_id, username, first_name, valid_ref)
        )
    if user_id == ADMIN_ID:
        c.execute("UPDATE users SET is_paid=1, payment_status='approved' WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return is_new_user


# ============== REFERRAL ==============
DEFAULT_REFERRAL_BONUS = 5000

def get_referral_bonus():
    try:
        return int(get_setting('referral_bonus', str(DEFAULT_REFERRAL_BONUS)))
    except (ValueError, TypeError):
        return DEFAULT_REFERRAL_BONUS


def get_user_referrer(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT referrer_id, bonus_credited FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 0, 0
    return row[0] or 0, row[1] or 0


def get_referral_stats(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT bonus_balance, total_bonus_earned, invited_count FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ? AND is_paid = 1', (user_id,))
    paid_refs = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (user_id,))
    total_refs = c.fetchone()[0]
    conn.close()
    bal, total_earned, _ = row if row else (0, 0, 0)
    return {'balance': bal or 0, 'total_earned': total_earned or 0, 'paid_refs': paid_refs, 'total_refs': total_refs}


def credit_referrer(referee_id):
    ref_id, credited = get_user_referrer(referee_id)
    if not ref_id or credited:
        return None
    bonus = get_referral_bonus()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET bonus_credited = 1 WHERE user_id = ? AND bonus_credited = 0', (referee_id,))
    if c.rowcount == 0:
        conn.close()
        return None
    c.execute(
        'UPDATE users SET bonus_balance = bonus_balance + ?, total_bonus_earned = total_bonus_earned + ?, invited_count = invited_count + 1 WHERE user_id = ?',
        (bonus, bonus, ref_id)
    )
    conn.commit()
    conn.close()
    return (ref_id, bonus)


def adjust_bonus(user_id, delta):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET bonus_balance = MAX(0, bonus_balance + ?) WHERE user_id = ?', (delta, user_id))
    conn.commit()
    conn.close()


def top_referrers(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        'SELECT user_id, username, first_name, invited_count, total_bonus_earned, bonus_balance FROM users WHERE invited_count > 0 ORDER BY invited_count DESC, total_bonus_earned DESC LIMIT ?',
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def set_payment_status(user_id, status, paid=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if paid is not None:
        c.execute('UPDATE users SET payment_status=?, is_paid=? WHERE user_id=?', (status, paid, user_id))
    else:
        c.execute('UPDATE users SET payment_status=? WHERE user_id=?', (status, user_id))
    conn.commit()
    conn.close()


def update_score(user_id, is_correct, question_id=None):
    stats = get_user_stats(user_id)
    if not stats:
        return None
    new_score = stats['score']
    new_correct = stats['correct_answers']
    new_streak = stats.get('streak', 0)
    best_streak = stats.get('best_streak', 0)
    wrong_cats = stats['wrong_categories']

    if is_correct:
        new_score = min(100, new_score + 5)
        new_correct += 1
        new_streak += 1
        if new_streak > best_streak:
            best_streak = new_streak
    else:
        new_score = max(0, new_score - 3)
        new_streak = 0
        if question_id is not None:
            key = str(question_id)
            wrong_cats[key] = wrong_cats.get(key, 0) + 1

    new_total = stats['total_questions'] + 1
    today = date.today().isoformat()
    last_active = stats.get('last_active') or ''
    daily_streak = stats.get('daily_streak', 0)
    if last_active != today:
        try:
            last_d = date.fromisoformat(last_active) if last_active else None
        except Exception:
            last_d = None
        if last_d and (date.today() - last_d).days == 1:
            daily_streak += 1
        else:
            daily_streak = 1

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE users SET score=?, total_questions=?, correct_answers=?, wrong_categories=?,
            streak=?, best_streak=?, last_active=?, daily_streak=?
        WHERE user_id=?
    ''', (new_score, new_total, new_correct, json.dumps(wrong_cats),
          new_streak, best_streak, today, daily_streak, user_id))
    conn.commit()
    conn.close()
    return get_user_stats(user_id)


def reset_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET score=0, total_questions=0, correct_answers=0, wrong_categories='{}', streak=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_leaderboard(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT first_name, username, score, correct_answers, total_questions FROM users WHERE total_questions > 0 ORDER BY score DESC, correct_answers DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def add_bookmark(user_id, question_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO bookmarks (user_id, question_id) VALUES (?, ?)', (user_id, question_id))
        conn.commit()
        ok = True
    except sqlite3.IntegrityError:
        ok = False
    conn.close()
    return ok


def get_bookmarks(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT question_id FROM bookmarks WHERE user_id = ?', (user_id,))
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    return ids


def get_total_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    n = c.fetchone()[0]
    conn.close()
    return n


def get_paid_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE is_paid = 1')
    n = c.fetchone()[0]
    conn.close()
    return n


def get_all_user_ids(only_paid=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if only_paid:
        c.execute('SELECT user_id FROM users WHERE is_paid = 1')
    else:
        c.execute('SELECT user_id FROM users')
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def is_paid(user_id):
    s = get_user_stats(user_id)
    return bool(s and s.get('is_paid'))


def _fix_question_obj(q):
    if isinstance(q, dict):
        if 'question' in q and isinstance(q['question'], str):
            q['question'] = fix_mojibake(q['question'])
        if 'description' in q and isinstance(q['description'], str):
            q['description'] = fix_mojibake(q['description'])
        if 'choices' in q and isinstance(q['choices'], list):
            q['choices'] = [fix_mojibake(c) if isinstance(c, str) else c for c in q['choices']]
    return q


def load_questions():
    with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return [_fix_question_obj(q) for q in data]


# ============== DARSLIKLAR (LESSONS) ==============
LESSON_TOPICS = [
    ("warn",          "⚠️ Ogohlantiruvchi belgilar"),
    ("priority",      "🔺 Ustunlik belgilari"),
    ("prohib",        "⛔ Taqiqlovchi belgilar"),
    ("mandate",       "🔵 Buyuruvchi belgilar"),
    ("info",          "🟦 Axborot-ko'rsatkich belgilari"),
    ("service",       "🛠 Servis belgilari"),
    ("addinfo",       "📋 Qo'shimcha axborot belgilari"),
    ("traffic_light", "🚦 Svetofor va chorrahalar"),
    ("controller",    "👮 Tartibga soluvchining ishoralari"),
    ("markings",      "🛣 Yo'l chiziqlari (razmetka)"),
    ("speed",         "🏎 Tezlik va xavfsiz masofa"),
    ("emergency",     "🚨 Avariya va tibbiy yordam"),
    ("other",         "📚 Boshqa darslar"),
]
TOPIC_TITLES = dict(LESSON_TOPICS)

# ============================================================
# BUILTIN_LESSONS — Admin qo'shmasdan ishlaydi (YouTube)
# ============================================================
BUILTIN_LESSONS = {
    "warn": [
        {
            "id": "warn_1",
            "title": "Ogohlantiruvchi belgilar — to'liq darslik",
            "url": "https://www.youtube.com/watch?v=Yb-q6g0q4PY",
            "desc": "YHQ bo'yicha ogohlantiruvchi belgilar batafsil ko'rib chiqiladi.",
        },
        {
            "id": "warn_2",
            "title": "Ogohlantiruvchi, imtiyoz va taqiqlovchi belgilar",
            "url": "https://www.youtube.com/watch?v=YEc2aK1tEXk",
            "desc": "Uch turdagi belgilar bitta darsda — solishtirma tushuntirish.",
        },
    ],
    "priority": [
        {
            "id": "priority_1",
            "title": "Ustunlik (imtiyoz) belgilari — to'liq tushuntirish",
            "url": "https://www.youtube.com/watch?v=YEc2aK1tEXk",
            "desc": "Ustunlik belgilarini qanday tanish va qachon berish kerak.",
        },
    ],
    "prohib": [
        {
            "id": "prohib_1",
            "title": "Taqiqlovchi belgilar — to'liq seriya (playlist)",
            "url": "https://www.youtube.com/playlist?list=PLEFFb9l03lEE2CiMVHcm1-Ku3Y4WuGgqT",
            "desc": "Taqiqlovchi belgilar to'liq seriyasi — barcha turlar batafsil.",
        },
        {
            "id": "prohib_2",
            "title": "Taqiqlovchi belgilar — 2-playlist",
            "url": "https://www.youtube.com/playlist?list=PLvYhWk1tm4D3rXxBQi2ees2RALCSoe1Af",
            "desc": "Qo'shimcha taqiqlovchi belgilar va amaliy misollar.",
        },
        {
            "id": "prohib_3",
            "title": "Ogohlantiruvchi, imtiyoz va taqiqlovchi belgilar",
            "url": "https://www.youtube.com/watch?v=YEc2aK1tEXk",
            "desc": "Uch turdagi belgilar solishtirmali tushuntirish.",
        },
    ],
    "mandate": [
        {
            "id": "mandate_1",
            "title": "Buyuruvchi belgilar (4.0) — to'liq darslik",
            "url": "https://www.youtube.com/watch?v=2E6FsZBK6d8",
            "desc": "YHQ bo'yicha buyuruvchi (majburiy) belgilar batafsil.",
        },
    ],
    "info": [
        {
            "id": "info_1",
            "title": "Axborot-ko'rsatkich belgilari",
            "url": "https://www.youtube.com/watch?v=ZHFxA-FIsv8",
            "desc": "Axborot va ko'rsatkich belgilari haqida to'liq tushuntirish.",
        },
        {
            "id": "info_2",
            "title": "Axborot ishora belgilari (5.0)",
            "url": "https://www.youtube.com/watch?v=eIgVVCuy2XA",
            "desc": "Axborot belgilarining yangi versiyasi bilan tanishing.",
        },
        {
            "id": "info_3",
            "title": "YHQ axborot-ishora belgilar (qo'shimcha dars)",
            "url": "https://www.youtube.com/watch?v=bVrYIRVP3i0",
            "desc": "Axborot-ishora belgilar bo'yicha qo'shimcha tushuntirish.",
        },
        {
            "id": "info_4",
            "title": "Axborot-ishora belgilar — to'liq playlist",
            "url": "https://www.youtube.com/playlist?list=PLfLuKHqgKPORVnY1Le4Eq_lMHsiBHznIC",
            "desc": "Barcha axborot belgilari ketma-ket — to'liq playlist.",
        },
    ],
    "service": [
        {
            "id": "service_1",
            "title": "Servis va axborot belgilari (to'liq playlist)",
            "url": "https://www.youtube.com/playlist?list=PLfLuKHqgKPORVnY1Le4Eq_lMHsiBHznIC",
            "desc": "Servis belgilarini ham o'z ichiga olgan to'liq playlist.",
        },
    ],
    "addinfo": [
        {
            "id": "addinfo_1",
            "title": "Qo'shimcha axborot belgilari va tartibga soluvchi ishoralari",
            "url": "https://www.youtube.com/watch?v=KNqQM8_tlEk",
            "desc": "Qo'shimcha belgilar va GAI ishoralari birga tushuntiriladi.",
        },
    ],
    "traffic_light": [
        {
            "id": "tl_1",
            "title": "Svetofor va tartibga soluvchi ishoralari — batafsil",
            "url": "https://www.youtube.com/watch?v=RrcCqcgnOQ0",
            "desc": "Svetofor va GAI ishoralari qanday o'qiladi — amaliy misollar.",
        },
        {
            "id": "tl_2",
            "title": "Svetofor va tartibga soluvchining ishoralari (online avtomaktab)",
            "url": "https://www.youtube.com/watch?v=AiTb9oBnrRM",
            "desc": "Online avtomaktab darsi — svetofor va GAI ishoralari.",
        },
    ],
    "controller": [
        {
            "id": "ctrl_1",
            "title": "Tartibga soluvchi (GAI) ishoralari — to'liq darslik",
            "url": "https://www.youtube.com/watch?v=6h01yJmBoTw",
            "desc": "GAI xodimining qo'l ishoralari batafsil ko'rsatiladi.",
        },
        {
            "id": "ctrl_2",
            "title": "Tartibga soluvchi ishoralari — 1-qism",
            "url": "https://www.youtube.com/watch?v=vc7b30DF81M",
            "desc": "Tartibga soluvchi ishoralarini bosqichma-bosqich o'rganing.",
        },
        {
            "id": "ctrl_3",
            "title": "Tartibga soluvchi (31-dars)",
            "url": "https://www.youtube.com/watch?v=hJ8fIR85aGU",
            "desc": "GAI ishoralari seriyasining 31-darsi.",
        },
        {
            "id": "ctrl_4",
            "title": "Tartibga soluvchi va svetofor — solishtirma darslik",
            "url": "https://www.youtube.com/watch?v=RrcCqcgnOQ0",
            "desc": "Tartibga soluvchi va svetofor ishoralarini birgalikda o'rganing.",
        },
    ],
    "markings": [
        {
            "id": "mark_1",
            "title": "Yo'l chiziqlari (razmetka) — to'liq seriya",
            "url": "https://www.youtube.com/playlist?list=PLyORhYq5Uzh7UcEFr69mlhdQtjnYIBawX",
            "desc": "Yo'l chiziqlari to'liq playlist — barcha turlari ketma-ket.",
        },
    ],
    "speed": [
        {
            "id": "speed_1",
            "title": "YHQ rasmiy matn — tezlik va xavfsiz masofa (lex.uz)",
            "url": "https://lex.uz/acts/-2850459",
            "desc": "Tezlik va xavfsiz masofa bo'yicha rasmiy qoidalar.",
        },
    ],
    "emergency": [
        {
            "id": "emerg_1",
            "title": "Avariya va tibbiy yordam — belgilar va qoidalar",
            "url": "https://www.youtube.com/watch?v=KNqQM8_tlEk",
            "desc": "Avariya vaziyatlarida yo'l harakati qoidalari.",
        },
    ],
    "other": [
        {
            "id": "other_1",
            "title": "YHQ to'liq matn — lex.uz rasmiy manba",
            "url": "https://lex.uz/acts/-2850459",
            "desc": "Yo'l harakati qoidalarining rasmiy to'liq matni.",
        },
        {
            "id": "other_3",
            "title": "Onlayn test — 24pdd.uz (o'zbek tilida)",
            "url": "https://24pdd.uz/ozb/",
            "desc": "YHQ savollari to'plami — o'zbek tilida.",
        },
    ],
}


def add_lesson(topic, title, file_id, file_type, added_by):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO lessons (topic, title, file_id, file_type, added_by) VALUES (?, ?, ?, ?, ?)',
              (topic, title, file_id, file_type, added_by))
    conn.commit()
    lesson_id = c.lastrowid
    conn.close()
    return lesson_id


def get_lessons_by_topic(topic):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, title, file_id, file_type FROM lessons WHERE topic = ? ORDER BY id DESC', (topic,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_lesson(lesson_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, topic, title, file_id, file_type FROM lessons WHERE id = ?', (lesson_id,))
    row = c.fetchone()
    conn.close()
    return row


def delete_lesson(lesson_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM lessons WHERE id = ?', (lesson_id,))
    conn.commit()
    conn.close()


def count_lessons_by_topic():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT topic, COUNT(*) FROM lessons GROUP BY topic')
    res = dict(c.fetchall())
    conn.close()
    return res


def count_builtin_by_topic():
    """Har bir mavzudagi builtin darslar soni."""
    return {k: len(v) for k, v in BUILTIN_LESSONS.items()}


# ============== FSM STATES ==============
class QuizStates(StatesGroup):
    waiting_answer = State()
    waiting_payment_screenshot = State()
    waiting_teacher_question = State()
    admin_upload_image = State()
    addq_text = State()
    addq_choices = State()
    addq_correct = State()
    addq_description = State()
    addq_image = State()
    addvideo_topic = State()
    addvideo_title = State()
    addvideo_media = State()


# ============== BOT ==============
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
print("TOKEN:", BOT_TOKEN)
BOT_USERNAME = "YHQ Avto tes"
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

questions = []
user_sessions = {}


def has_available_image(question):
    media = question.get('media') or {}

    if not media.get('exist'):
        return True  # rasm kerak emas

    name = media.get('name')
    local_path = find_local_image(name)

    return bool(local_path)  # faqat lokal fayl bor bo‘lsa TRUE


def usable_questions():
    return [q for q in questions if has_available_image(q)]


def progress_bar(score, width=10):
    filled = int(round(score / 100 * width))
    return "█" * filled + "░" * (width - filled)


def main_menu_keyboard():
    rows = [
        [InlineKeyboardButton(text="📖 Oddiy rejim", callback_data="mode_normal"),
         InlineKeyboardButton(text="🎯 Pro rejim", callback_data="mode_pro")],
        [InlineKeyboardButton(text="⚡ Blits (10 ta savol)", callback_data="mode_blitz")],
    ]
    if lessons_visible():
        rows.append([InlineKeyboardButton(text="📺 Darsliklar (video)", callback_data="lessons")])
    rows += [
        [InlineKeyboardButton(text="🔖 Saqlangan savollar", callback_data="bookmarks"),
         InlineKeyboardButton(text="🏆 Reyting", callback_data="leaderboard")],
        [InlineKeyboardButton(text="📈 Statistika", callback_data="stats"),
         InlineKeyboardButton(text="❓ Yordam", callback_data="help")],
    ]
    if referral_visible():
        rows.append([InlineKeyboardButton(text="🎁 Do'stni taklif qilish (BONUS)", callback_data="referral")])
    rows += [
        [InlineKeyboardButton(text="👨‍🏫 Ustozga murojat", callback_data="ask_teacher_general")],
        [InlineKeyboardButton(text="🔄 Ballarni tiklash", callback_data="reset_score")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ To'lov qildim (chek yuborish)", callback_data="paid_send_check")],
        [InlineKeyboardButton(text="📞 Adminga murojat", url=f"https://t.me/{ADMIN_USERNAME}")],
        [InlineKeyboardButton(text="🔄 Holatni tekshirish", callback_data="check_payment")],
    ])


def build_payment_text():
    return (
        "🚗 <b>Yo'l Harakati Qoidalari Boti</b>\n\n"
        "👋 Botdan foydalanish uchun bir martalik to'lov talab qilinadi.\n\n"
        f"💰 <b>Narxi:</b> {PRICE_UZS:,} so'm\n"
        f"💳 <b>Karta raqami:</b> <code>{CARD_NUMBER}</code>\n"
        + (f"👤 <b>Karta egasi:</b> {esc(CARD_HOLDER)}\n" if CARD_HOLDER else "")
        + "\n📌 <b>Tartib:</b>\n"
        f"1. Yuqoridagi kartaga {PRICE_UZS:,} so'm o'tkazing\n"
        "2. <b>«To'lov qildim»</b> tugmasini bosing\n"
        "3. To'lov chekining (skrinshot) rasmini yuboring\n"
        "4. Admin tasdiqlagandan so'ng bot ochiladi\n\n"
        f"❓ Savol/muammo bo'lsa: @{ADMIN_USERNAME}"
    )


def build_start_text(stats, name):
    ready = "✅ <b>Siz imtihonga tayyorsiz!</b>" if stats['score'] >= 80 else "📚 Yana mashq qiling..."
    avail = len(usable_questions())
    return (
        f"🚗 <b>Yo'l Harakati Qoidalari Boti</b>\n\n"
        f"Salom, <b>{esc(name)}</b>! 👋\n\n"
        f"📊 <b>Sizning statistikangiz:</b>\n"
        f"• Ball: <b>{stats['score']}/100</b>  {progress_bar(stats['score'])}\n"
        f"• Jami savollar: <b>{stats['total_questions']}</b>\n"
        f"• To'g'ri javoblar: <b>{stats['correct_answers']}</b>\n"
        f"• Hozirgi seriya: <b>{stats.get('streak', 0)}</b> 🔥  "
        f"(Eng yaxshisi: <b>{stats.get('best_streak', 0)}</b>)\n"
        f"• Kunlik faollik: <b>{stats.get('daily_streak', 0)}</b> kun\n\n"
        f"{ready}\n\n"
        f"📚 Hozir mavjud savollar: <b>{avail}</b> ta\n\n"
        f"Rejim tanlang:"
    )


async def show_payment_screen(message, edit=False):
    text = build_payment_text()
    kb = payment_keyboard()
    try:
        if edit:
            await message.edit_text(text, reply_markup=kb)
        else:
            await message.answer(text, reply_markup=kb)
    except Exception:
        await message.answer(text, reply_markup=kb)


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject = None):
    try:
        await state.clear()
    except Exception:
        pass
    user = message.from_user
    referrer_id = 0
    if command and command.args:
        arg = command.args.strip()
        if arg.isdigit():
            try:
                referrer_id = int(arg)
            except ValueError:
                referrer_id = 0
    try:
        is_new_user = create_or_update_user(user.id, user.username or "", user.first_name or "Foydalanuvchi", referrer_id=referrer_id)
        stats = get_user_stats(user.id) or {}
    except Exception as e:
        logger.error(f"/start DB error: {e}")
        await message.answer("⏳ Bot ishga tushmoqda, 1 daqiqadan so'ng /start bosing.")
        return

    if is_new_user and referrer_id:
        actual_ref, _ = get_user_referrer(user.id)
        if actual_ref:
            try:
                new_name = user.first_name or user.username or f"ID {user.id}"
                await bot.send_message(
                    actual_ref,
                    f"👋 <b>Yangi do'stingiz qo'shildi!</b>\n\n"
                    f"Sizning linkingiz orqali <b>{esc(new_name)}</b> botga kirdi.\n\n"
                    f"💡 U to'lov qilganidan so'ng sizga <b>{get_referral_bonus():,} so'm</b> bonus avtomatik beriladi."
                )
            except Exception as e:
                logger.warning(f"New referee notify failed: {e}")

    if not stats.get('is_paid'):
        if stats.get('payment_status') == 'pending':
            await message.answer(
                "⏳ <b>To'lovingiz tekshirilmoqda...</b>\n\n"
                "Admin tasdiqlashini kuting. Odatda bu 5-30 daqiqa vaqt oladi.\n"
                f"Shoshilinch holat: @{ADMIN_USERNAME}\n"
            )
            return
        await show_payment_screen(message, edit=False)
        return

    name = user.first_name or user.username or "do'st"
    await message.answer(build_start_text(stats, name), reply_markup=main_menu_keyboard())


@dp.callback_query(F.data == "paid_send_check")
async def paid_send_check(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(QuizStates.waiting_payment_screenshot)
    await callback.message.answer(
        "📸 <b>To'lov chekining rasmini yuboring</b>\n\n"
        "Skrinshot yoki rasmda quyidagilar ko'rinishi kerak:\n"
        "• To'lov summasi\n"
        "• Sana va vaqt\n"
        "• Karta raqami\n\n"
        "Rasm sifatida yuboring (faylga emas, oddiy rasmga o'xshab)."
    )


@dp.message(QuizStates.waiting_payment_screenshot, F.photo)
async def receive_payment_screenshot(message: types.Message, state: FSMContext):
    user = message.from_user
    photo = message.photo[-1]
    file_id = photo.file_id
    set_payment_status(user.id, 'pending', paid=0)
    caption = (
        f"💳 <b>Yangi to'lov cheki</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> {esc(user.first_name or '')} "
        f"{('@' + esc(user.username)) if user.username else ''}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"💰 Summa: {PRICE_UZS:,} so'm\n"
        f"📅 Sana: {now_tash().strftime('%Y-%m-%d %H:%M')} (Toshkent)"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"pay_approve_{user.id}"),
         InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay_reject_{user.id}")],
    ])
    try:
        await bot.send_photo(ADMIN_ID, photo=file_id, caption=caption, reply_markup=kb)
    except Exception as e:
        logger.error(f"Admin photo send error: {e}")
    await state.clear()
    await message.answer(
        "✅ <b>Chek qabul qilindi!</b>\n\n"
        "Admin tekshirib, tasdiqlaydi. Tasdiqlanganidan so'ng sizga xabar keladi.\n"
        f"Savol bo'lsa: @{ADMIN_USERNAME}"
    )


@dp.message(QuizStates.waiting_payment_screenshot, ~F.text.startswith('/'))
async def wrong_payment_input(message: types.Message):
    await message.answer("❗ Iltimos, to'lov chekining <b>rasmini</b> yuboring (matn emas).")


async def _notify_referrer_after_payment(referee_id):
    res = credit_referrer(referee_id)
    if not res:
        return
    ref_id, bonus = res
    referee_stats = get_user_stats(referee_id) or {}
    referee_name = referee_stats.get('first_name') or referee_stats.get('username') or f"ID {referee_id}"
    rs = get_referral_stats(ref_id)
    try:
        await bot.send_message(
            ref_id,
            f"🎁 <b>Yangi bonus oldingiz!</b>\n\n"
            f"Siz taklif qilgan <b>{esc(referee_name)}</b> botga to'lov qildi.\n\n"
            f"💰 Bonus: <b>+{bonus:,} so'm</b>\n"
            f"💳 Joriy balans: <b>{rs['balance']:,} so'm</b>\n"
            f"👥 Jami taklif qilingan: <b>{rs['paid_refs']}</b> ta\n\n"
            f"Bonusni olish uchun admin bilan bog'laning: @{ADMIN_USERNAME}"
        )
    except Exception as e:
        logger.warning(f"Referrer notify failed: {e}")
    try:
        ref_user = get_user_stats(ref_id) or {}
        ref_name = ref_user.get('first_name') or ref_user.get('username') or f"ID {ref_id}"
        await bot.send_message(
            ADMIN_ID,
            f"🎁 <b>Bonus berildi</b>\n\n"
            f"👤 Taklif qilgan: <b>{esc(ref_name)}</b> (<code>{ref_id}</code>)\n"
            f"👤 Yangi to'lovchi: {esc(referee_name)} (<code>{referee_id}</code>)\n"
            f"💰 Bonus summasi: <b>+{bonus:,} so'm</b>\n"
            f"💳 Yangi balansi: <b>{rs['balance']:,} so'm</b>"
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("pay_approve_"))
async def admin_approve_payment(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin uchun", show_alert=True)
        return
    user_id = int(callback.data.split("_")[2])
    set_payment_status(user_id, 'approved', paid=1)
    await callback.answer("✅ Tasdiqlandi")
    try:
        await callback.message.edit_caption((callback.message.caption or "") + "\n\n✅ <b>TASDIQLANDI</b>", reply_markup=None)
    except Exception:
        pass
    try:
        await bot.send_message(user_id, "🎉 <b>To'lovingiz tasdiqlandi!</b>\n\nEndi botdan to'liq foydalanishingiz mumkin.\n👇 Boshlash uchun /start bosing.")
    except Exception as e:
        logger.error(f"Notify user error: {e}")
    await _notify_referrer_after_payment(user_id)


@dp.callback_query(F.data.startswith("pay_reject_"))
async def admin_reject_payment(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin uchun", show_alert=True)
        return
    user_id = int(callback.data.split("_")[2])
    set_payment_status(user_id, 'rejected', paid=0)
    await callback.answer("❌ Rad etildi")
    try:
        await callback.message.edit_caption((callback.message.caption or "") + "\n\n❌ <b>RAD ETILDI</b>", reply_markup=None)
    except Exception:
        pass
    try:
        await bot.send_message(user_id, f"❌ <b>To'lov rad etildi</b>\n\nIltimos, chekni qayta yuboring yoki admin bilan bog'laning.\nAdmin: @{ADMIN_USERNAME}\n\nQayta urinish uchun /start bosing.")
    except Exception:
        pass


@dp.callback_query(F.data == "check_payment")
async def check_payment_status(callback: CallbackQuery):
    stats = get_user_stats(callback.from_user.id)
    if stats and stats.get('is_paid'):
        await callback.answer("✅ To'lov tasdiqlangan! /start bosing", show_alert=True)
    elif stats and stats.get('payment_status') == 'pending':
        await callback.answer("⏳ To'lov tekshirilmoqda. Biroz kuting.", show_alert=True)
    else:
        await callback.answer("❌ Hali to'lov tasdiqlanmagan", show_alert=True)


@dp.message(Command("approve"))
async def admin_approve_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Foydalanish: /approve <user_id>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await message.answer("Noto'g'ri ID")
        return
    set_payment_status(uid, 'approved', paid=1)
    await message.answer(f"✅ {uid} ochildi")
    try:
        await bot.send_message(uid, "🎉 To'lovingiz tasdiqlandi! /start bosing.")
    except Exception:
        pass
    await _notify_referrer_after_payment(uid)


@dp.message(Command("revoke"))
async def admin_revoke_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Foydalanish: /revoke <user_id>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        return
    set_payment_status(uid, 'none', paid=0)
    await message.answer(f"🚫 {uid} foydalanuvchi yopildi")


@dp.message(Command("upload"))
async def admin_upload_cmd(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("📤 Foydalanish: <code>/upload &lt;savol_id&gt;</code>\nMisol: <code>/upload 5</code>")
        return
    arg = parts[1].strip()
    if '-' in arg:
        try:
            a, b = arg.split('-', 1)
            start_id, end_id = int(a), int(b)
            await state.set_state(QuizStates.admin_upload_image)
            await state.update_data(range_start=start_id, range_end=end_id, range_cur=start_id)
            await message.answer(f"📥 Rasmlarni ketma-ket yuboring.\nBirinchi #{start_id} ga... #{end_id} gacha.\n\nTo'xtatish: /cancel")
            return
        except ValueError:
            await message.answer("❗ Diapazon noto'g'ri. Misol: /upload 1-50")
            return
    try:
        qid = int(arg)
    except ValueError:
        await message.answer("❗ Savol ID raqam bo'lishi kerak")
        return
    await state.set_state(QuizStates.admin_upload_image)
    await state.update_data(target_id=qid)
    await message.answer(f"📥 Savol <b>#{qid}</b> uchun rasmni yuboring.\nTo'xtatish: /cancel")


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    cur = await state.get_state()
    if cur:
        await state.clear()
        await message.answer("❌ Bekor qilindi")


@dp.message(Command("done"))
async def cmd_done(message: types.Message, state: FSMContext):
    cur = await state.get_state()
    if cur == QuizStates.admin_upload_image.state:
        await state.clear()
        await message.answer("✅ Rasm yuklash tugatildi")


@dp.message(QuizStates.admin_upload_image, F.photo)
async def admin_receive_image(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    if 'range_cur' in data:
        cur = data['range_cur']
        end = data['range_end']
        await save_question_image(message, cur)
        nxt = cur + 1
        if nxt > end:
            await state.clear()
            await message.answer(f"✅ Diapazon tugadi ({data['range_start']}–{end}). Yuklash yakunlandi.")
        else:
            await state.update_data(range_cur=nxt)
            await message.answer(f"✅ #{cur} saqlandi. Endi #{nxt} uchun rasm yuboring.")
        return
    qid = data.get('target_id')
    if qid is None:
        await message.answer("❗ Avval /upload <id> bering")
        await state.clear()
        return
    await save_question_image(message, qid)
    await state.clear()
    await message.answer(f"✅ Savol <b>#{qid}</b> uchun rasm saqlandi.\n\nYana yuklash: /upload &lt;id&gt;")


async def save_question_image(message: types.Message, qid: int):
    os.makedirs(IMAGES_DIR, exist_ok=True)
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    for ext in IMAGE_EXTS:
        old = os.path.join(IMAGES_DIR, f"{qid}{ext}")
        if os.path.exists(old):
            try:
                os.remove(old)
            except Exception:
                pass
    dst = os.path.join(IMAGES_DIR, f"{qid}.jpg")
    await bot.download_file(file.file_path, destination=dst)


@dp.message(F.photo, F.caption.regexp(r'^\s*(\d+)\s*$'))
async def admin_caption_upload(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    cur = await state.get_state()
    if cur is not None:
        return
    try:
        qid = int(message.caption.strip())
    except ValueError:
        return
    await save_question_image(message, qid)
    await message.answer(f"✅ Rasm savol <b>#{qid}</b> ga saqlandi")


@dp.message(Command("images"))
async def admin_images_status(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    with_images = sum(1 for q in questions if (q.get('media') or {}).get('exist'))
    without_images = len(questions) - with_images
    text = (
        f"🖼 <b>Rasmlar holati</b>\n\n"
        f"📚 Jami savollar: <b>{len(questions)}</b>\n"
        f"✅ Rasmi mavjud: <b>{with_images}</b> ({100*with_images//len(questions)}%)\n"
        f"❌ Rasmsiz: <b>{without_images}</b> ({100*without_images//len(questions)}%)\n\n"
        f"<b>Qo'shish usullari:</b>\n"
        f"1️⃣ /nextimage\n2️⃣ /upload 1\n3️⃣ /upload 1-50\n"
    )
    await message.answer(text)


def save_questions_to_file():
    with open(QUESTIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)


def find_question_by_id(qid):
    try:
        qid = int(qid)
    except Exception:
        return None
    for q in questions:
        if q.get('id') == qid:
            return q
    return None


def set_correct_answer(qid, choice_index):
    q = find_question_by_id(qid)
    if not q:
        return False, "Savol topilmadi"
    choices = q.get('choises', [])
    if choice_index < 0 or choice_index >= len(choices):
        return False, f"Variant raqami noto'g'ri (1..{len(choices)} bo'lishi kerak)"
    for i, c in enumerate(choices):
        c['answer'] = (i == choice_index)
    save_questions_to_file()
    return True, choices[choice_index].get('text', '')


@dp.message(Command("fixq"))
async def admin_fixq_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or '').split()
    if len(parts) < 2:
        await message.answer(
            "📝 <b>Javobni tuzatish</b>\n\n"
            "Foydalanish:\n"
            "<code>/fixq &lt;savol_id&gt;</code> — variantlarni ko'rish\n"
            "<code>/fixq &lt;savol_id&gt; &lt;raqam&gt;</code> — to'g'ri javobni belgilash\n\n"
            "Misol: <code>/fixq 156 3</code>"
        )
        return
    q = find_question_by_id(parts[1])
    if not q:
        await message.answer(f"❌ #{esc(parts[1])} ID li savol topilmadi")
        return
    if len(parts) == 2:
        text = f"❓ <b>Savol #{q.get('id')}</b>\n\n{esc(q.get('question',''))}\n\n<b>Variantlar:</b>\n"
        kb_rows = []
        for i, c in enumerate(q.get('choises', [])):
            mark = "✅" if c.get('answer') else "▫️"
            text += f"\n<b>{i+1})</b> {mark} {esc(c.get('text',''))}"
            kb_rows.append([InlineKeyboardButton(
                text=f"{i+1}-variantni to'g'ri qilish",
                callback_data=f"setans_{q.get('id')}_{i}"
            )])
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        return
    try:
        idx = int(parts[2]) - 1
    except Exception:
        await message.answer("❌ Raqam noto'g'ri")
        return
    ok, info = set_correct_answer(q.get('id'), idx)
    if ok:
        await message.answer(f"✅ Saqlandi.\n\nSavol #{q.get('id')} uchun yangi to'g'ri javob:\n➜ <b>{esc(info)}</b>")
    else:
        await message.answer(f"❌ {info}")


@dp.callback_query(F.data.startswith("setans_"))
async def admin_setans_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin", show_alert=True)
        return
    try:
        _, qid, idx = callback.data.split("_")
        qid = int(qid); idx = int(idx)
    except Exception:
        await callback.answer("Xato", show_alert=True)
        return
    ok, info = set_correct_answer(qid, idx)
    if ok:
        await callback.answer("✅ Saqlandi", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(f"✅ Savol #{qid} uchun yangi to'g'ri javob:\n➜ <b>{esc(info)}</b>")
    else:
        await callback.answer(info, show_alert=True)


@dp.callback_query(F.data.startswith("adminfix_"))
async def admin_fix_open_cb(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Faqat admin", show_alert=True)
        return
    try:
        qid = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Xato", show_alert=True)
        return
    q = find_question_by_id(qid)
    if not q:
        await callback.answer("Savol topilmadi", show_alert=True)
        return
    text = f"✏️ <b>Savol #{qid} javobini tuzatish</b>\n\n{esc(q.get('question',''))}\n\n<b>To'g'ri variantni tanlang:</b>\n"
    kb_rows = []
    for i, c in enumerate(q.get('choises', [])):
        mark = "✅" if c.get('answer') else "▫️"
        text += f"\n<b>{i+1})</b> {mark} {esc(c.get('text',''))}"
        kb_rows.append([InlineKeyboardButton(
            text=f"{i+1}",
            callback_data=f"setans_{qid}_{i}"
        )])
    await callback.answer()
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.message(Command("addq"))
async def admin_addq_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(QuizStates.addq_text)
    await message.answer("➕ <b>Yangi savol qo'shish</b>\n\n1-bosqich: Savol matnini yozing.\n\nBekor qilish: /cancel")


@dp.message(QuizStates.addq_text, ~F.text.startswith('/'))
async def addq_get_text(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("❗ Matn bo'sh. Qayta yozing.")
        return
    await state.update_data(q_text=txt)
    await state.set_state(QuizStates.addq_choices)
    await message.answer("✅ Savol matni saqlandi.\n\n2-bosqich: Javob variantlarini <b>har birini yangi qatorga</b> yozing (2-6 ta).")


@dp.message(QuizStates.addq_choices, ~F.text.startswith('/'))
async def addq_get_choices(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    lines = [l.strip() for l in (message.text or "").split('\n') if l.strip()]
    if len(lines) < 2 or len(lines) > 6:
        await message.answer("❗ 2 dan 6 tagacha variant kiriting.")
        return
    await state.update_data(q_choices=lines)
    letters = ['A', 'B', 'C', 'D', 'E', 'F'][:len(lines)]
    preview = "\n".join(f"<b>{letters[i]})</b> {esc(lines[i])}" for i in range(len(lines)))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=letters[i], callback_data=f"addq_correct_{i}") for i in range(len(lines))]])
    await state.set_state(QuizStates.addq_correct)
    await message.answer("3-bosqich: <b>To'g'ri javob</b> qaysi?\n\n" + preview, reply_markup=kb)


@dp.callback_query(QuizStates.addq_correct, F.data.startswith("addq_correct_"))
async def addq_pick_correct(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    idx = int(callback.data.split("_")[2])
    await state.update_data(q_correct=idx)
    await state.set_state(QuizStates.addq_description)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="O'tkazib yuborish", callback_data="addq_no_desc")]])
    await callback.answer("✅ Tanlandi")
    await callback.message.answer("4-bosqich: <b>Izoh</b> kiriting yoki o'tkazib yuboring:", reply_markup=kb)


@dp.callback_query(QuizStates.addq_description, F.data == "addq_no_desc")
async def addq_skip_desc(callback: CallbackQuery, state: FSMContext):
    await state.update_data(q_desc="")
    await callback.answer()
    await ask_addq_image(callback.message, state)


@dp.message(QuizStates.addq_description, ~F.text.startswith('/'))
async def addq_get_desc(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.update_data(q_desc=(message.text or "").strip())
    await ask_addq_image(message, state)


async def ask_addq_image(message, state):
    await state.set_state(QuizStates.addq_image)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Rasmsiz saqlash", callback_data="addq_no_img")]])
    await message.answer("5-bosqich: <b>Rasm</b> yuboring yoki rasmsiz saqlang:", reply_markup=kb)


@dp.callback_query(QuizStates.addq_image, F.data == "addq_no_img")
async def addq_finish_no_img(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await finalize_new_question(callback.message, state, photo_msg=None)


@dp.message(QuizStates.addq_image, F.photo)
async def addq_finish_with_img(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await finalize_new_question(message, state, photo_msg=message)


async def finalize_new_question(message, state, photo_msg=None):
    data = await state.get_data()
    new_id = max((q.get('id', 0) for q in questions), default=0) + 1
    choices = [{"text": t, "answer": (i == data['q_correct'])} for i, t in enumerate(data['q_choices'])]
    media = {"exist": False, "name": ""}
    if photo_msg:
        await save_question_image(photo_msg, new_id)
        media = {"exist": True, "name": str(new_id)}
    new_q = {"id": new_id, "question": data['q_text'], "choises": choices, "media": media, "description": data.get('q_desc') or ""}
    questions.append(new_q)
    save_questions_to_file()
    await state.clear()
    await message.answer(f"✅ <b>Yangi savol qo'shildi!</b>\n\n🆔 ID: <b>{new_id}</b>\n📝 {esc(new_q['question'])}\n📚 Jami savollar: <b>{len(questions)}</b>")


@dp.message(Command("nextimage"))
async def admin_next_image(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    needed = [q for q in questions if (q.get('media') or {}).get('exist')]
    missing = [q for q in needed if not find_local_image(q['media'].get('name'))]
    if not missing:
        await message.answer("🎉 Hamma rasmlar mavjud!")
        return
    q = missing[0]
    qid = q['id']
    letters = ['A', 'B', 'C', 'D', 'E', 'F']
    text = f"📸 <b>Rasm kerak — Savol #{qid}</b>\n\n❓ {esc(q.get('question',''))}\n\n<b>Variantlar:</b>"
    for i, ch in enumerate(q.get('choises', [])):
        mark = " ✅" if ch.get('answer') else ""
        text += f"\n{letters[i]}) {esc(ch.get('text',''))}{mark}"
    text += f"\n\nQolgan rasmsiz savollar: <b>{len(missing)}</b> ta"
    await state.set_state(QuizStates.admin_upload_image)
    await state.update_data(target_id=qid, next_image_mode=True)
    await message.answer(text)


@dp.message(Command("skip"))
async def admin_skip_image(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    cur = await state.get_state()
    data = await state.get_data()
    if cur == QuizStates.admin_upload_image.state and data.get('next_image_mode'):
        await state.clear()
        await message.answer("⏭ O'tkazildi. Keyingisi: /nextimage")


@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    builtin_total = sum(len(v) for v in BUILTIN_LESSONS.values())
    await message.answer(
        f"🛠 <b>Admin panel</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{get_total_users()}</b>\n"
        f"💰 To'langan: <b>{get_paid_users()}</b>\n\n"
        f"📚 Jami savollar: <b>{len(questions)}</b>\n\n"
        f"🎬 Builtin YouTube darslar: <b>{builtin_total}</b> ta (admin kerak emas)\n\n"
        f"<b>To'lovlar:</b>\n"
        f"/pending — kutilayotgan to'lovlar\n"
        f"/approve &lt;user_id&gt; — qo'lda ochish\n"
        f"/revoke &lt;user_id&gt; — yopish\n\n"
        f"<b>Savollar:</b>\n"
        f"/addq — yangi savol\n"
        f"/fixq &lt;id&gt; — noto'g'ri javobni tuzatish\n"
        f"/upload &lt;id&gt; — rasm yuklash\n"
        f"/nextimage — rasmsiz savolga rasm\n"
        f"/images — rasmlar holati\n"
        f"/fixtext — xato belgilarni tuzatish\n\n"
        f"<b>Darsliklar:</b>\n"
        f"/addvideo — admin video qo'shish\n"
        f"/lessons — darsliklar holati\n"
        f"/dellesson &lt;id&gt; — o'chirish\n"
        f"/togglelessons — ko'rsatish/yashirish\n\n"
        f"<b>Menyu tugmalari:</b>\n"
        f"/togglereferral — \"Do'stni taklif qilish\" tugmasini yoqish/o'chirish "
        f"(hozir: <b>{'YOQILGAN ✅' if referral_visible() else 'OCHIRILGAN ❌'}</b>)\n\n"
        f"<b>E'lon:</b>\n"
        f"/sendall — to'lagan userlarga\n"
        f"/sendallusers — hammasiga\n\n"
        f"<b>Referral:</b>\n"
        f"/refstats — TOP taklifchilar\n"
        f"/setbonus &lt;summa&gt; — bonus o'zgartirish\n"
        f"/paybonus &lt;user_id&gt; &lt;summa&gt; — naqd to'langanini belgilash"
    )


async def show_main_menu(target_message, user, edit=True):
    create_or_update_user(user.id, user.username or "", user.first_name or "Foydalanuvchi")
    stats = get_user_stats(user.id)
    if not stats.get('is_paid'):
        await show_payment_screen(target_message, edit=edit)
        return
    name = user.first_name or user.username or "do'st"
    text = build_start_text(stats, name)
    try:
        if edit:
            await target_message.edit_text(text, reply_markup=main_menu_keyboard())
        else:
            await target_message.answer(text, reply_markup=main_menu_keyboard())
    except Exception:
        await target_message.answer(text, reply_markup=main_menu_keyboard())


import functools
import inspect

def require_paid(func):
    sig = inspect.signature(func)
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    allowed = set(sig.parameters.keys())

    @functools.wraps(func)
    async def wrapper(callback: CallbackQuery, *args, **kwargs):
        if not is_paid(callback.from_user.id):
            await callback.answer("To'lov talab qilinadi. /start bosing.", show_alert=True)
            return
        if not accepts_kwargs:
            kwargs = {k: v for k, v in kwargs.items() if k in allowed}
        return await func(callback, *args, **kwargs)
    return wrapper


@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await show_main_menu(callback.message, callback.from_user, edit=True)


@dp.callback_query(F.data == "stats")
@require_paid
async def show_stats(callback: CallbackQuery):
    stats = get_user_stats(callback.from_user.id)
    accuracy = round((stats['correct_answers'] / max(stats['total_questions'], 1)) * 100)
    text = (
        f"📊 <b>Batafsil statistika</b>\n\n"
        f"👤 <b>{esc(stats.get('first_name') or stats.get('username') or 'Foydalanuvchi')}</b>\n"
        f"🎯 Ball: <b>{stats['score']}/100</b>  {progress_bar(stats['score'])}\n"
        f"📝 Jami savollar: <b>{stats['total_questions']}</b>\n"
        f"✅ To'g'ri: <b>{stats['correct_answers']}</b>\n"
        f"❌ Noto'g'ri: <b>{stats['total_questions'] - stats['correct_answers']}</b>\n"
        f"📈 Aniqlik: <b>{accuracy}%</b>\n"
        f"🔥 Hozirgi seriya: <b>{stats.get('streak', 0)}</b>\n"
        f"🏅 Eng uzun seriya: <b>{stats.get('best_streak', 0)}</b>\n"
        f"📅 Kunlik faollik: <b>{stats.get('daily_streak', 0)}</b> kun\n"
    )
    if stats['wrong_categories']:
        text += "\n📌 <b>Eng ko'p xato qilingan savollar:</b>\n"
        for qid, count in sorted(stats['wrong_categories'].items(), key=lambda x: x[1], reverse=True)[:5]:
            text += f"  • Savol #{esc(qid)}: {count} marta\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="main_menu")]])
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "leaderboard")
@require_paid
async def show_leaderboard(callback: CallbackQuery):
    rows = get_leaderboard(10)
    text = "🏆 <b>TOP 10 — Eng faol o'quvchilar</b>\n\n"
    if not rows:
        text += "Hozircha bo'sh. Birinchi bo'ling!"
    else:
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        for i, (first_name, username, score, correct, total) in enumerate(rows):
            name = first_name or username or "Anonim"
            acc = round((correct / max(total, 1)) * 100)
            text += f"{medals[i]} <b>{esc(name)}</b> — {score}/100 ({correct}/{total}, {acc}%)\n"
    text += f"\n👥 Jami foydalanuvchilar: <b>{get_total_users()}</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="main_menu")]])
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text(HELP_TEXT, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="main_menu")]]
        ))
    except Exception:
        await callback.message.answer(HELP_TEXT)


@dp.callback_query(F.data == "reset_score")
@require_paid
async def reset_score_cb(callback: CallbackQuery, state: FSMContext):
    reset_user(callback.from_user.id)
    await callback.answer("✅ Statistika tiklandi!", show_alert=True)
    await state.clear()
    await show_main_menu(callback.message, callback.from_user, edit=True)


@dp.callback_query(F.data == "bookmarks")
@require_paid
async def show_bookmarks(callback: CallbackQuery, state: FSMContext):
    ids = get_bookmarks(callback.from_user.id)
    if not ids:
        await callback.answer("Saqlangan savollar yo'q", show_alert=True)
        return
    user_sessions[callback.from_user.id] = {
        'mode': 'bookmarks',
        'questions': [q for q in questions if q['id'] in ids and has_available_image(q)],
        'current_question': None, 'wrong_count': 0, 'asked': 0, 'correct_in_session': 0,
    }
    await callback.answer()
    await callback.message.edit_text(f"🔖 <b>Saqlangan savollar:</b> {len(ids)} ta\n\nBoshlaymiz...")
    await state.set_state(QuizStates.waiting_answer)
    await send_next_question(callback.from_user.id, callback.message, state)


@dp.callback_query(F.data.in_(["mode_normal", "mode_pro", "mode_blitz"]))
@require_paid
async def choose_mode(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    mode = callback.data.split("_")[1]
    pool = usable_questions()
    if not pool:
        await callback.answer("Hozircha foydalanish mumkin bo'lgan savol yo'q", show_alert=True)
        return
    random.shuffle(pool)
    pool = pool[:10] if mode == "blitz" else pool[:20]
    user_sessions[user_id] = {'mode': mode, 'questions': pool, 'current_question': None, 'wrong_count': 0, 'asked': 0, 'correct_in_session': 0}
    if mode == "pro":
        intro = "🎯 <b>PRO rejim</b>\n⚠️ Xato qilsangiz, qo'shimcha savollar beriladi.\n\nBoshladik!"
    elif mode == "blitz":
        intro = "⚡ <b>BLITS rejim</b>\n10 ta savolga tez javob bering!\n\nBoshladik!"
    else:
        intro = "📖 <b>ODDIY rejim</b>\n20 ta savol tayyor.\n\nBoshladik!"
    await callback.answer()
    await callback.message.edit_text(intro)
    await state.set_state(QuizStates.waiting_answer)
    await send_next_question(user_id, callback.message, state)


async def send_next_question(user_id, message, state):
    session = user_sessions.get(user_id)
    if not session or not session['questions']:
        await finish_quiz(user_id, message, state)
        return
    question = session['questions'].pop(0)
    session['current_question'] = question
    session['asked'] += 1

    q_text = question.get('question', '')
    text = (
        f"❓ <b>Savol #{esc(question.get('id'))}</b>  "
        f"<i>({session['asked']}-savol)</i>\n\n"
        f"{esc(q_text)}"
    )
    choices = question.get('choises', []).copy()
    random.shuffle(choices)
    session['current_choices'] = choices

    letters = ['A', 'B', 'C', 'D', 'E', 'F']
    text += "\n\n<b>Javob variantlari:</b>"
    for i, ch in enumerate(choices):
        text += f"\n<b>{letters[i]})</b> {highlight_keywords(ch.get('text',''))}"

    buttons = []
    row = []
    for i in range(len(choices)):
        row.append(InlineKeyboardButton(text=letters[i], callback_data=f"ans_{i}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton(text="🔖 Saqlash", callback_data="bookmark_current"),
        InlineKeyboardButton(text="⏭ O'tkazish", callback_data="skip"),
    ])
    buttons.append([InlineKeyboardButton(text="👨‍🏫 Ustozga murojat", callback_data="ask_teacher_q")])
    buttons.append([InlineKeyboardButton(text="🛑 To'xtatish", callback_data="main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    media = question.get('media') or {}
    sent_photo = False

    if media.get('exist'):
        name = media.get('name')
        local_path = find_local_image(name)

    # 🔥 1. AVVAL URL (TO‘G‘RI)
        if IMAGE_BASE_URL and name:
            url = get_image_url(name)
            try:
                await message.answer_photo(photo=url)
                sent_photo = True
            except Exception as e:
                logger.warning(f"Remote image error {url}: {e}")

    # 🔥 2. KEYIN LOCAL (FALLBACK)
        if not sent_photo and local_path:
            try:
                await message.answer_photo(photo=types.FSInputFile(local_path))
                sent_photo = True
            except Exception as e:
                logger.warning(f"Local image error {name}: {e}")

    # 🔥 3. UMUMAN BO‘LMASA
        if not sent_photo:
            text = "🖼 <i>(rasm mavjud emas)</i>\n\n" + text

    # 🔥 SAVOL MATNI VA TUGMALARNI YUBORISH
    try:
        await message.answer(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Savol yuborishda xatolik: {e}")


async def finish_quiz(user_id, message, state):
    session = user_sessions.get(user_id, {})
    stats = get_user_stats(user_id) or {'score': 0, 'correct_answers': 0, 'total_questions': 0}
    asked = session.get('asked', 0)
    correct_in_session = session.get('correct_in_session', 0)
    sess_acc = round((correct_in_session / max(asked, 1)) * 100)
    text = (
        f"🎉 <b>Quiz tugadi!</b>\n\n"
        f"📊 <b>Sessiya natijasi:</b>\n"
        f"• Berilgan savollar: <b>{asked}</b>\n"
        f"• To'g'ri javoblar: <b>{correct_in_session}</b>\n"
        f"• Aniqlik: <b>{sess_acc}%</b>\n\n"
        f"📈 <b>Umumiy ball:</b> <b>{stats['score']}/100</b>  {progress_bar(stats['score'])}\n\n"
        f"{'✅ <b>Siz imtihonga tayyorsiz!</b> 🎓' if stats['score'] >= 80 else '📚 Yana mashq qiling!'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yana boshlash", callback_data="mode_normal")],
        [InlineKeyboardButton(text="🏆 Reyting", callback_data="leaderboard")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu")],
    ])
    await message.answer(text, reply_markup=kb)
    user_sessions.pop(user_id, None)
    await state.clear()


@dp.callback_query(F.data == "skip")
@require_paid
async def skip_question(callback: CallbackQuery, state: FSMContext):
    await callback.answer("⏭ O'tkazildi")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_next_question(callback.from_user.id, callback.message, state)


@dp.callback_query(F.data == "bookmark_current")
@require_paid
async def bookmark_current(callback: CallbackQuery):
    session = user_sessions.get(callback.from_user.id)
    if not session or not session.get('current_question'):
        await callback.answer("Saqlash uchun savol yo'q", show_alert=True)
        return
    qid = session['current_question'].get('id')
    ok = add_bookmark(callback.from_user.id, qid)
    await callback.answer("🔖 Saqlandi!" if ok else "Allaqachon saqlangan", show_alert=True)


@dp.callback_query(F.data.in_(["ask_teacher_q", "ask_teacher_general"]))
@require_paid
async def ask_teacher(callback: CallbackQuery, state: FSMContext):
    session = user_sessions.get(callback.from_user.id)
    ctx_qid = None
    if callback.data == "ask_teacher_q" and session and session.get('current_question'):
        ctx_qid = session['current_question'].get('id')
    await state.set_state(QuizStates.waiting_teacher_question)
    await state.update_data(question_id=ctx_qid)
    await callback.answer()
    extra = f"\n\n📌 Savol #{ctx_qid} bo'yicha so'rovingiz yuboriladi." if ctx_qid else ""
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_teacher")]])
    await callback.message.answer("👨‍🏫 <b>Ustozga murojat</b>\n\nSavolingiz yoki tushunmagan joyingizni yozing." + extra, reply_markup=kb)


@dp.callback_query(F.data == "cancel_teacher")
async def cancel_teacher(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Bekor qilindi")
    await show_main_menu(callback.message, callback.from_user, edit=False)


@dp.message(QuizStates.waiting_teacher_question, ~F.text.startswith('/'))
async def forward_to_teacher(message: types.Message, state: FSMContext):
    if not is_paid(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    qid = data.get('question_id')
    user = message.from_user
    head = (
        f"👨‍🎓 <b>Yangi savol — o'quvchidan</b>\n\n"
        f"👤 <b>{esc(user.first_name or '')}</b> {('@' + esc(user.username)) if user.username else ''}\n"
        f"🆔 <code>{user.id}</code>\n"
    )
    full_q = None
    if qid is not None:
        full_q = next((q for q in questions if q.get('id') == qid), None)
    if full_q:
        letters = ['A', 'B', 'C', 'D', 'E', 'F']
        q_block = f"\n📌 <b>Savol #{qid}:</b>\n{esc(full_q.get('question',''))}\n\n<b>Variantlar:</b>\n"
        for i, ch in enumerate(full_q.get('choises', [])):
            mark = " ✅" if ch.get('answer') else ""
            q_block += f"{letters[i]}) {esc(ch.get('text',''))}{mark}\n"
        if full_q.get('description'):
            q_block += f"\n💡 <i>Izoh: {esc(full_q['description'])}</i>"
        head += q_block
    head += f"\n\n💬 <b>O'quvchining xabari:</b>\n{esc(message.text or '(matnsiz)')}"
    try:
        sent = False
        if full_q:
            media = full_q.get('media') or {}
            if media.get('exist'):
                local = find_local_image(media.get('name'))
                if local:
                    try:
                        await bot.send_photo(USTOZ_ID, photo=types.FSInputFile(local), caption=head[:1024])
                        if len(head) > 1024:
                            await bot.send_message(USTOZ_ID, head[1024:])
                        sent = True
                    except Exception as e:
                        logger.warning(f"Teacher photo send failed: {e}")
        if not sent:
            await bot.send_message(USTOZ_ID, head)
        if message.content_type != 'text':
            await message.copy_to(USTOZ_ID)
        await message.answer("✅ <b>Murojaatingiz ustozga yuborildi!</b>\n\nTez orada javob oladi degan umiddamiz.")
    except Exception as e:
        logger.error(f"Teacher forward error: {e}")
        await message.answer(f"❌ Yuborishda xatolik. To'g'ridan-to'g'ri yozing: @{ADMIN_USERNAME}")
    await state.clear()
    session = user_sessions.get(user.id)
    if session and session.get('questions'):
        await state.set_state(QuizStates.waiting_answer)
        await send_next_question(user.id, message, state)
    else:
        await show_main_menu(message, user, edit=False)


@dp.message(F.reply_to_message, F.from_user.id == USTOZ_ID)
async def teacher_reply(message: types.Message):
    src = message.reply_to_message
    if not src:
        return
    src_text = src.text or src.caption or ""
    if not src_text:
        return
    target_id = None
    for line in src_text.split('\n'):
        if '🆔' in line:
            digits = ''.join(c for c in line if c.isdigit())
            if digits:
                try:
                    target_id = int(digits)
                except ValueError:
                    pass
            break
    if not target_id:
        return
    try:
        reply_text = message.text or message.caption or ""
        if reply_text:
            await bot.send_message(target_id, f"👨‍🏫 <b>Ustozdan javob:</b>\n\n{esc(reply_text)}")
        if message.content_type != 'text':
            await message.copy_to(target_id)
        await message.reply("✅ Yuborildi")
    except Exception as e:
        await message.reply(f"❌ Xatolik: {e}")


# ============================================================
# DARSLIKLAR — FOYDALANUVCHI (YANGILANGAN)
# ============================================================
def lessons_topics_keyboard():
    db_counts = count_lessons_by_topic()
    builtin_counts = count_builtin_by_topic()
    rows = []
    for key, title in LESSON_TOPICS:
        db_n = db_counts.get(key, 0)
        bi_n = builtin_counts.get(key, 0)
        total = db_n + bi_n
        rows.append([InlineKeyboardButton(
            text=f"{title}  ({total} dars)",
            callback_data=f"lt_{key}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "lessons")
@require_paid
async def show_lessons_menu(callback: CallbackQuery):
    await callback.answer()
    builtin_total = sum(len(v) for v in BUILTIN_LESSONS.values())
    text = (
        "📺 <b>Darsliklar</b>\n\n"
        f"🎬 YouTube darslar: <b>{builtin_total}</b> ta (hoziroq ko'rish mumkin)\n\n"
        "Mavzuni tanlang:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=lessons_topics_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=lessons_topics_keyboard())


@dp.callback_query(F.data.startswith("lt_"))
@require_paid
async def show_topic_lessons(callback: CallbackQuery):
    topic = callback.data[3:]
    title = TOPIC_TITLES.get(topic, "Mavzu")
    await callback.answer()

    # DB darslar (admin qo'shganlari)
    db_rows = get_lessons_by_topic(topic)
    # Builtin YouTube darslar
    builtin = BUILTIN_LESSONS.get(topic, [])

    if not db_rows and not builtin:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Mavzular", callback_data="lessons")],
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu")],
        ])
        await callback.message.edit_text(
            f"{title}\n\nHozircha bu mavzuda dars yo'q.",
            reply_markup=kb
        )
        return

    total = len(db_rows) + len(builtin)
    buttons = []

    # Admin qo'shgan darslar (bot ichida)
    for r in db_rows:
        buttons.append([InlineKeyboardButton(
            text=f"▶️ {r[1][:50]}",
            callback_data=f"lp_{r[0]}"
        )])

    # Builtin YouTube darslar
    for item in builtin:
        buttons.append([InlineKeyboardButton(
            text=f"🎬 {item['title'][:48]}",
            callback_data=f"lbi_{topic}|{item['id']}"
        )])

    buttons.append([InlineKeyboardButton(text="⬅️ Mavzular", callback_data="lessons")])
    buttons.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu")])

    legend = ""
    if db_rows and builtin:
        legend = "\n▶️ — Bot ichidagi video\n🎬 — YouTube darsi\n"
    elif builtin:
        legend = "\n🎬 — YouTube darslar (tashqi havola)\n"
    elif db_rows:
        legend = "\n▶️ — Bot ichidagi video\n"

    await callback.message.edit_text(
        f"<b>{title}</b>\n\n"
        f"📚 Jami: <b>{total}</b> ta dars"
        f"{legend}\n"
        f"Darsni tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ============================================================
# BUILTIN DARS OCHISH (YouTube)
# ============================================================
@dp.callback_query(F.data.startswith("lbi_"))
async def play_builtin_lesson(callback: CallbackQuery):
    if not is_paid(callback.from_user.id):
        await callback.answer("To'lov talab qilinadi. /start bosing.", show_alert=True)
        return

    # Format: lbi_<topic>|<lesson_id>
    raw = callback.data[4:]  # "lbi_" ni olib tashlaymiz
    if "|" not in raw:
        await callback.answer("Noto'g'ri format", show_alert=True)
        return

    topic, lesson_id = raw.split("|", 1)
    topic_items = BUILTIN_LESSONS.get(topic, [])
    found_item = next((item for item in topic_items if item["id"] == lesson_id), None)

    if not found_item:
        await callback.answer("Dars topilmadi", show_alert=True)
        return

    topic_title = TOPIC_TITLES.get(topic, "")
    text = (
        f"🎬 <b>{esc(found_item['title'])}</b>\n\n"
        f"📂 <i>{esc(topic_title)}</i>\n\n"
        f"📝 {esc(found_item['desc'])}\n\n"
        f"👇 Pastdagi tugmani bosib YouTube da oching:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="▶️ YouTube da ko'rish",
            url=found_item["url"]
        )],
        [InlineKeyboardButton(
            text="⬅️ Orqaga",
            callback_data=f"lt_{topic}"
        )],
        [InlineKeyboardButton(
            text="🏠 Bosh menyu",
            callback_data="main_menu"
        )],
    ])
    await callback.answer()
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


# ============================================================
# ADMIN DARS OCHISH (bot ichida saqlangan fayllar)
# ============================================================
@dp.callback_query(F.data.startswith("lp_"))
async def play_lesson(callback: CallbackQuery):
    if not is_paid(callback.from_user.id):
        await callback.answer("To'lov talab qilinadi. /start bosing.", show_alert=True)
        return
    try:
        lid = int(callback.data[3:])
    except (ValueError, IndexError):
        await callback.answer("Noto'g'ri ID", show_alert=True)
        return
    row = get_lesson(lid)
    if not row:
        await callback.answer("Dars topilmadi", show_alert=True)
        return
    _id, topic, title, file_id, file_type = row
    await callback.answer("⏳ Yuborilmoqda...")
    cap = f"📺 <b>{esc(title)}</b>\n📂 {TOPIC_TITLES.get(topic, '')}"
    chat_id = callback.message.chat.id
    last_err = None
    senders = []
    if file_type == 'video':
        senders = [
            lambda: bot.send_video(chat_id, video=file_id, caption=cap),
            lambda: bot.send_document(chat_id, document=file_id, caption=cap),
        ]
    elif file_type == 'document':
        senders = [lambda: bot.send_document(chat_id, document=file_id, caption=cap)]
    elif file_type == 'photo':
        senders = [lambda: bot.send_photo(chat_id, photo=file_id, caption=cap)]
    elif file_type == 'animation':
        senders = [
            lambda: bot.send_animation(chat_id, animation=file_id, caption=cap),
            lambda: bot.send_document(chat_id, document=file_id, caption=cap),
        ]
    elif file_type == 'video_note':
        senders = [lambda: bot.send_video_note(chat_id, video_note=file_id)]
    else:
        await bot.send_message(chat_id, cap)
        return
    for fn in senders:
        try:
            await fn()
            if file_type == 'video_note':
                await bot.send_message(chat_id, cap)
            return
        except Exception as e:
            last_err = e
            logger.error(f"Lesson {lid} play error ({file_type}): {e}")
    await bot.send_message(chat_id, f"❌ Faylni yuborishda xatolik.\nAdmin (@{ADMIN_USERNAME}) ga murojat qiling. ID: <code>{lid}</code>")


# ============================================================
# ADMIN: DARSLIKLAR BOSHQARUVI
# ============================================================
@dp.message(Command("addvideo"))
async def admin_addvideo_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(QuizStates.addvideo_topic)
    rows = [[InlineKeyboardButton(text=t, callback_data=f"av_topic_{k}")] for k, t in LESSON_TOPICS]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="av_cancel")])
    await message.answer("📥 <b>Yangi dars qo'shish</b>\n\n1-bosqich: Mavzuni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data == "av_cancel")
async def av_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Bekor qilindi")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@dp.callback_query(QuizStates.addvideo_topic, F.data.startswith("av_topic_"))
async def av_pick_topic(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    topic = callback.data[len("av_topic_"):]
    await state.update_data(topic=topic)
    await state.set_state(QuizStates.addvideo_title)
    await callback.answer("✅")
    await callback.message.answer(f"Mavzu: <b>{TOPIC_TITLES.get(topic, topic)}</b>\n\n2-bosqich: Dars uchun <b>nom</b> yozing.")


@dp.message(QuizStates.addvideo_title, ~F.text.startswith('/'))
async def av_get_title(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    title = (message.text or "").strip()
    if not title or len(title) > 200:
        await message.answer("❗ Sarlavha 1-200 belgi orasida bo'lishi kerak.")
        return
    await state.update_data(title=title)
    await state.set_state(QuizStates.addvideo_media)
    await message.answer("3-bosqich: <b>Video</b> (yoki rasm/hujjat/GIF) yuboring.\n\nBekor qilish: /cancel")


@dp.message(QuizStates.addvideo_media, ~F.text.startswith('/'))
async def av_save_media(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    file_id, file_type = None, None
    if message.video:
        file_id, file_type = message.video.file_id, 'video'
    elif message.document:
        file_id, file_type = message.document.file_id, 'document'
    elif message.animation:
        file_id, file_type = message.animation.file_id, 'animation'
    elif message.video_note:
        file_id, file_type = message.video_note.file_id, 'video_note'
    elif message.photo:
        file_id, file_type = message.photo[-1].file_id, 'photo'
    else:
        await message.answer("❗ Video / hujjat / GIF / rasm yuboring.")
        return
    data = await state.get_data()
    topic = data['topic']
    title = data['title']
    lid = add_lesson(topic, title, file_id, file_type, message.from_user.id)
    await state.clear()
    await message.answer(f"✅ <b>Dars qo'shildi!</b>\n\n🆔 <code>{lid}</code>\n📂 {TOPIC_TITLES.get(topic)}\n📺 {esc(title)}\n🎬 Tur: {file_type}\n\nYana: /addvideo\nO'chirish: /dellesson {lid}")


@dp.message(Command("dellesson"))
async def admin_del_lesson(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Foydalanish: /dellesson <id>", parse_mode=None)
        return
    try:
        lid = int(parts[1])
    except ValueError:
        await message.answer("Noto'g'ri ID")
        return
    row = get_lesson(lid)
    if not row:
        await message.answer("Dars topilmadi")
        return
    delete_lesson(lid)
    await message.answer(f"🗑 Dars #{lid} o'chirildi: {esc(row[2])}")


@dp.message(Command("lessons"))
async def admin_list_lessons(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    db_counts = count_lessons_by_topic()
    builtin_counts = count_builtin_by_topic()
    text = "📚 <b>Darsliklar holati</b>\n\n"
    db_total = 0
    bi_total = 0
    for key, title in LESSON_TOPICS:
        db_n = db_counts.get(key, 0)
        bi_n = builtin_counts.get(key, 0)
        db_total += db_n
        bi_total += bi_n
        text += f"{title}:\n  🎬 Builtin: {bi_n} | ▶️ Admin: {db_n}\n"
    text += (
        f"\n📊 Jami builtin (YouTube): <b>{bi_total}</b>\n"
        f"📊 Jami admin qo'shgan: <b>{db_total}</b>\n\n"
        f"👁 Ko'rsatish: <b>{'YOQILGAN ✅' if lessons_visible() else 'OCHIRILGAN ❌'}</b>\n"
        f"Almashtirish: /togglelessons"
    )
    await message.answer(text)


@dp.message(Command("togglelessons"))
async def admin_toggle_lessons(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    cur = lessons_visible()
    set_setting('lessons_visible', '0' if cur else '1')
    new = lessons_visible()
    await message.answer(f"{'✅ Darsliklar YOQILDI' if new else '❌ Darsliklar YASHIRILDI'}")


@dp.message(Command("togglereferral"))
async def admin_toggle_referral(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    cur = referral_visible()
    set_setting('referral_visible', '0' if cur else '1')
    new = referral_visible()
    msg = "✅ Do'stni taklif qilish tugmasi YOQILDI" if new else "❌ Do'stni taklif qilish tugmasi OCHIRILDI"
    await message.answer(msg)


@dp.message(Command("pending"))
async def admin_pending(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    rows = get_pending_payments()
    if not rows:
        await message.answer("✅ Kutilayotgan to'lov yo'q.")
        return
    await message.answer(f"⏳ <b>Kutilayotgan to'lovlar: {len(rows)}</b>")
    for uid, uname, fname in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"pay_approve_{uid}"),
             InlineKeyboardButton(text="❌ Rad etish", callback_data=f"pay_reject_{uid}")],
        ])
        info = f"👤 {esc(fname or '')} {('@' + esc(uname)) if uname else ''}\n🆔 ID: <code>{uid}</code>"
        await message.answer(info, reply_markup=kb)


@dp.message(Command("fixtext"))
async def admin_fix_text(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("⏳ Tekshiryapman...")
    fixed_count = 0
    for q in questions:
        before = json.dumps(q, ensure_ascii=False)
        _fix_question_obj(q)
        after = json.dumps(q, ensure_ascii=False)
        if before != after:
            fixed_count += 1
    save_questions_to_file()
    await message.answer(f"✅ Tugadi.\n\nTuzatilgan savollar: <b>{fixed_count}</b> / {len(questions)}")


async def _do_broadcast(message: types.Message, only_paid: bool):
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        cmd = parts[0] if parts else "/sendall"
        await message.answer(f"Foydalanish: <code>{cmd} salom hammaga!</code>")
        return
    body = parts[1].strip()
    user_ids = get_all_user_ids(only_paid=only_paid)
    if not user_ids:
        await message.answer("Hech kim topilmadi.")
        return
    target_kind = "to'lov qilgan" if only_paid else "barcha"
    status = await message.answer(f"📢 Yuborilmoqda... {len(user_ids)} ta ({target_kind})")
    sent, failed = 0, 0
    import asyncio as _asyncio
    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.send_message(uid, f"📢 <b>E'lon</b>\n\n{esc(body)}")
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast to {uid} failed: {e}")
        await _asyncio.sleep(0.04)
        if i % 25 == 0:
            try:
                await status.edit_text(f"📢 {i}/{len(user_ids)}\n✅ {sent} | ❌ {failed}")
            except Exception:
                pass
    await status.edit_text(f"✅ <b>Tugadi.</b>\n📨 Yuborildi: <b>{sent}</b>\n❌ Yetkazilmadi: <b>{failed}</b>")


@dp.message(Command("sendall"))
async def admin_sendall_paid(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await _do_broadcast(message, only_paid=True)


@dp.message(Command("sendallusers"))
async def admin_sendall_everyone(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await _do_broadcast(message, only_paid=False)


def _build_referral_text(user_id, name):
    rs = get_referral_stats(user_id)
    bonus = get_referral_bonus()
    link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    pending = rs['total_refs'] - rs['paid_refs']
    return (
        f"🎁 <b>Do'stni taklif qil — pul ishla!</b>\n\n"
        f"Salom, <b>{esc(name)}</b>! 👋\n\n"
        f"💰 Har bir do'stingiz to'lov qilsa, sizga <b>{bonus:,} so'm</b> bonus beriladi.\n\n"
        f"<b>📊 Sizning statistikangiz:</b>\n"
        f"👥 Ro'yxatdan o'tganlar: <b>{rs['total_refs']}</b>\n"
        f"✅ To'lov qilganlar: <b>{rs['paid_refs']}</b>\n"
        f"⏳ Kutilmoqda: <b>{pending}</b>\n"
        f"💳 Bonus balansingiz: <b>{rs['balance']:,} so'm</b>\n"
        f"🏆 Jami yutuq: <b>{rs['total_earned']:,} so'm</b>\n\n"
        f"<b>🔗 Sizning shaxsiy linkingiz:</b>\n"
        f"<code>{link}</code>\n\n"
        f"📤 Linkni do'stlaringizga yuboring.\n\n"
        f"💵 Bonusni naqdga aylantirish: @{ADMIN_USERNAME}"
    )


@dp.callback_query(F.data == "referral")
@require_paid
async def show_referral(callback: CallbackQuery):
    await callback.answer()
    name = callback.from_user.first_name or callback.from_user.username or "do'st"
    text = _build_referral_text(callback.from_user.id, name)
    link = f"https://t.me/{BOT_USERNAME}?start={callback.from_user.id}"
    from urllib.parse import quote
    share_text = (
        "🚗 @YHQAkademiyaBot — haydovchilikni 0 dan o'rganing!\n\n"
        "📚 Endi faqat test emas — TO'LIQ DARSLIK + AMALIYOT bir joyda!\n\n"
        "🎯 Sizni nimalar kutmoqda:\n"
        "📖 700+ YHQ savollar (imtihonga tayyorlaydi)\n"
        "🚦 Yo'l belgilarini o'rganish (oddiy va tushunarli)\n"
        "👮 GAI ishoralari (amaliy tushuntirish bilan)\n"
        "🚥 Svetafor darslari (real vaziyatlar bilan)\n"
        "🎥 Video darsliklar (hammasi bosqichma-bosqich)\n\n"
        "💯 Test + Darslik = 100% tayyorgarlik!\n\n"
        "🔥 3 xil rejim:\n"
        "• Oddiy\n"
        "• Pro\n"
        "• Blits ⚡\n\n"
        "🏆 Reyting | 🔖 Saqlash | 📊 Statistika | 👨‍🏫 Ustozga murojaat\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🎁 BONUS AKSIYA:\n"
        "👥 Do'stingizni taklif qiling\n"
        "💰 Har biri uchun 5 000 so'm oling!\n\n"
        "⏳ Faqat cheklangan vaqt!\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🚀 Hoziroq boshlang:\n"
        f"👉 {link}"
    )
    share_url = f"https://t.me/share/url?url={quote(link)}&text={quote(share_text)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Do'stlarga ulashish", url=share_url)],
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="referral")],
        [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="main_menu")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@dp.message(Command("invite"))
async def cmd_invite(message: types.Message):
    if not is_paid(message.from_user.id):
        await message.answer("To'lov talab qilinadi. /start bosing.")
        return
    name = message.from_user.first_name or message.from_user.username or "do'st"
    await message.answer(_build_referral_text(message.from_user.id, name), disable_web_page_preview=True)


@dp.message(Command("refstats"))
async def admin_ref_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    rows = top_referrers(limit=20)
    if not rows:
        await message.answer("📊 Hali hech kim do'st taklif qilmadi.")
        return
    text = f"🏆 <b>TOP TAKLIFCHILAR</b> (bonus: {get_referral_bonus():,} so'm)\n\n"
    for i, (uid, uname, fname, n, earned, bal) in enumerate(rows, 1):
        nm = fname or uname or f"ID {uid}"
        un = f" @{uname}" if uname else ""
        text += f"{i}. <b>{esc(nm)}</b>{un}\n   👥 {n} ta | 💰 {earned:,} so'm | 💳 {bal:,} balans\n   🆔 <code>{uid}</code>\n\n"
    await message.answer(text)


@dp.message(Command("setbonus"))
async def admin_set_bonus(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(f"Hozirgi bonus: <b>{get_referral_bonus():,} so'm</b>\n\nO'zgartirish: <code>/setbonus 5000</code>")
        return
    try:
        new_bonus = int(parts[1].replace(',', '').replace(' ', ''))
    except ValueError:
        await message.answer("Noto'g'ri summa")
        return
    if new_bonus < 0 or new_bonus > 1_000_000:
        await message.answer("Summa 0-1,000,000 orasida bo'lishi kerak")
        return
    set_setting('referral_bonus', str(new_bonus))
    await message.answer(f"✅ Yangi bonus: <b>{new_bonus:,} so'm</b>")


@dp.message(Command("paybonus"))
async def admin_pay_bonus(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Foydalanish: <code>/paybonus &lt;user_id&gt; &lt;summa&gt;</code>")
        return
    try:
        uid = int(parts[1])
        amt = int(parts[2].replace(',', '').replace(' ', ''))
    except ValueError:
        await message.answer("Noto'g'ri qiymat")
        return
    rs = get_referral_stats(uid)
    if amt > rs['balance']:
        await message.answer(f"❌ Balans yetarli emas. Joriy: {rs['balance']:,} so'm")
        return
    adjust_bonus(uid, -amt)
    new_rs = get_referral_stats(uid)
    await message.answer(f"✅ Ayirildi: <b>{amt:,} so'm</b>\n💳 Yangi balans: <b>{new_rs['balance']:,} so'm</b>")
    try:
        await bot.send_message(uid, f"💵 <b>Bonusingiz to'landi!</b>\n\nSumma: <b>{amt:,} so'm</b>\n💳 Qolgan: <b>{new_rs['balance']:,} so'm</b>")
    except Exception:
        pass


@dp.message(F.text)
async def catch_all_text(message: types.Message, state: FSMContext):
    cur = await state.get_state()
    if cur:
        return
    if message.from_user.id == ADMIN_ID:
        return
    if not is_paid(message.from_user.id):
        await message.answer("To'lov talab qilinadi. Boshlash uchun /start bosing.")
    else:
        await message.answer("Asosiy menyu uchun /start bosing.")


@dp.callback_query(F.data.startswith("ans_"))
@require_paid
async def process_answer(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    session = user_sessions.get(user_id)
    if not session or not session.get('current_question'):
        await callback.answer("❌ Sessiya tugadi! /start bosing", show_alert=True)
        return
    try:
        choice_index = int(callback.data.split("_")[1])
    except Exception:
        await callback.answer("Xato", show_alert=True)
        return
    choices = session.get('current_choices', [])
    if choice_index >= len(choices):
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return

    question = session['current_question']
    selected = choices[choice_index]
    is_correct = bool(selected.get('answer'))
    new_stats = update_score(user_id, is_correct, question.get('id'))
    if is_correct:
        session['correct_in_session'] = session.get('correct_in_session', 0) + 1

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if is_correct:
        result = "✅ <b>To'g'ri!</b>"
        if new_stats and new_stats.get('streak', 0) >= 3:
            result += f"  🔥 <b>{new_stats['streak']}</b> qatorasiga!"
    else:
        correct_text = ""
        for ch in choices:
            if ch.get('answer'):
                correct_text = ch.get('text', '')
                break
        result = f"❌ <b>Noto'g'ri!</b>\n\n📝 To'g'ri javob:\n➜ {highlight_keywords(correct_text)}"
        if question.get('description'):
            result += f"\n\n💡 <b>Izoh:</b>\n{highlight_keywords(question['description'])}"
        if session['mode'] == 'pro' and session['wrong_count'] == 0:
            session['wrong_count'] = 1
            qid = question.get('id', 0)
            pool = [q for q in usable_questions() if q.get('id') != qid]
            random.shuffle(pool)
            session['questions'] = pool[:3] + session['questions']
            result += "\n\n⚠️ <b>Pro rejim:</b> qo'shimcha 3 ta savol qo'shildi."

    if new_stats:
        result += f"\n\n📊 Ball: <b>{new_stats['score']}/100</b>  {progress_bar(new_stats['score'])}"

    await callback.answer()
    fix_kb = None
    if user_id == ADMIN_ID:
        qid = question.get('id')
        fix_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✏️ Javobni tuzatish", callback_data=f"adminfix_{qid}")
        ]])
    await callback.message.answer(result, reply_markup=fix_kb)
    await send_next_question(user_id, callback.message, state)


HELP_TEXT = (
    "📖 <b>YO'L HARAKATI BOTI — QO'LLANMA</b>\n\n"
    "🎯 <b>Rejimlar:</b>\n"
    "• <b>Oddiy</b> — 20 ta tasodifiy savol\n"
    "• <b>Pro</b> — xato qilsangiz, qo'shimcha savollar\n"
    "• <b>Blits</b> — 10 ta savol, tezlik uchun\n\n"
    "💯 <b>Ball:</b> +5 to'g'ri uchun, -3 noto'g'ri uchun (0–100)\n"
    "🔥 <b>Seriya:</b> ketma-ket to'g'ri javoblar\n"
    "🔖 <b>Bookmark:</b> qiyin savollarni saqlang\n"
    "🏆 <b>Reyting:</b> boshqa o'quvchilar bilan raqobat\n"
    "📺 <b>Darsliklar:</b> YouTube video darslar (tekin!)\n"
    "👨‍🏫 <b>Ustozga murojat:</b> har bir savol ostida tugma\n\n"
    "<b>Buyruqlar:</b>\n"
    "/start — bosh menyu\n"
    "/help — yordam\n"
    "/leaderboard — reyting\n"
    "/stats — statistika\n"
    "/invite — do'stlarni taklif qilish"
)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT)


@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: types.Message):
    if not is_paid(message.from_user.id):
        await message.answer("To'lov talab qilinadi. /start bosing.")
        return
    rows = get_leaderboard(10)
    text = "🏆 <b>TOP 10</b>\n\n"
    if not rows:
        text += "Hozircha bo'sh."
    else:
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        for i, (first_name, username, score, correct, total) in enumerate(rows):
            name = first_name or username or "Anonim"
            acc = round((correct / max(total, 1)) * 100)
            text += f"{medals[i]} <b>{esc(name)}</b> — {score}/100 ({correct}/{total}, {acc}%)\n"
    await message.answer(text)


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not is_paid(message.from_user.id):
        await message.answer("To'lov talab qilinadi. /start bosing.")
        return
    stats = get_user_stats(message.from_user.id)
    accuracy = round((stats['correct_answers'] / max(stats['total_questions'], 1)) * 100)
    text = (
        f"📊 <b>Sizning statistikangiz</b>\n\n"
        f"🎯 Ball: <b>{stats['score']}/100</b>  {progress_bar(stats['score'])}\n"
        f"📝 Jami: <b>{stats['total_questions']}</b>\n"
        f"✅ To'g'ri: <b>{stats['correct_answers']}</b>\n"
        f"📈 Aniqlik: <b>{accuracy}%</b>\n"
        f"🔥 Seriya: <b>{stats.get('streak', 0)}</b> (eng yaxshi: {stats.get('best_streak', 0)})\n"
        f"📅 Kunlik faollik: <b>{stats.get('daily_streak', 0)}</b> kun"
    )
    await message.answer(text)


async def main():
    global questions, BOT_USERNAME
    init_db()
    questions = load_questions()
    logger.info(f"✅ {len(questions)} savol yuklandi")
    builtin_total = sum(len(v) for v in BUILTIN_LESSONS.values())
    logger.info(f"🎬 {builtin_total} ta builtin YouTube darsi yuklandi")
    try:
        me = await bot.get_me()
        if me and me.username:
            BOT_USERNAME = me.username
            logger.info(f"🤖 Bot username: @{BOT_USERNAME}")
    except Exception as e:
        logger.warning(f"get_me failed: {e}")
    logger.info("🤖 Bot ishga tushmoqda...")
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())