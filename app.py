import os
import json
import requests
from flask import Flask, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, date
import calendar
import jpholiday

app = Flask(__name__, static_folder='static')

CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_GROUP_ID = os.environ.get('LINE_GROUP_ID', '')
BASE_URL = os.environ.get('BASE_URL', 'https://your-app.onrender.com')

DATA_FILE = 'schedules.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_weekends_and_holidays(year, month):
    """指定月の土日祝日を取得"""
    days = []
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        for i, day in enumerate(week):
            if day == 0:
                continue
            d = date(year, month, day)
            is_weekend = i >= 5  # 土(5)日(6)
            is_holiday = jpholiday.is_holiday(d)
            if is_weekend or is_holiday:
                days.append(d.strftime('%Y-%m-%d'))
    return days

def send_line_message(text):
    """LINEグループにメッセージを送信"""
    if not LINE_GROUP_ID or not CHANNEL_ACCESS_TOKEN:
        print("LINE credentials not set")
        return
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'
    }
    payload = {
        'to': LINE_GROUP_ID,
        'messages': [{'type': 'text', 'text': text}]
    }
    resp = requests.post(
        'https://api.line.me/v2/bot/message/push',
        headers=headers,
        json=payload
    )
    print(f"LINE send status: {resp.status_code}, {resp.text}")

def create_schedule_for_next_month():
    """翌月の日程調整データを作成してLINEに通知"""
    today = date.today()
    if today.month == 12:
        next_year, next_month = today.year + 1, 1
    else:
        next_year, next_month = today.year, today.month + 1

    month_key = f"{next_year}-{next_month:02d}"
    data = load_data()

    days = get_weekends_and_holidays(next_year, next_month)
    data[month_key] = {
        'year': next_year,
        'month': next_month,
        'days': days,
        'votes': {},
        'created_at': datetime.now().isoformat()
    }
    save_data(data)

    url = f"{BASE_URL}/schedule/{month_key}"
    month_name = f"{next_year}年{next_month}月"
    message = (
        f"🗓 {month_name}の日程調整を開始します！\n\n"
        f"土日祝の都合を教えてください⚾\n\n"
        f"📝 回答はこちら👇\n{url}\n\n"
        f"締め切り：{next_year}年{next_month}月10日"
    )
    send_line_message(message)
    print(f"Created schedule for {month_key}")

def send_reminder():
    """催促メッセージを送信（毎月9日）"""
    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"
    url = f"{BASE_URL}/schedule/{month_key}"
    message = (
        f"⚠️ 締め切りは明日なので投票してない人はよろしく！\n\n"
        f"📝 回答はこちら👇\n{url}"
    )
    send_line_message(message)

# --- スケジューラー設定 ---
scheduler = BackgroundScheduler(timezone='Asia/Tokyo')
# 毎月5日 朝9時に翌月の日程調整を送信
scheduler.add_job(create_schedule_for_next_month, 'cron', day=5, hour=9, minute=0)
# 毎月9日 朝9時に催促メッセージを送信
scheduler.add_job(send_reminder, 'cron', day=9, hour=9, minute=0)
scheduler.start()

# --- API エンドポイント ---

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/schedule/<month_key>')
def schedule_page(month_key):
    return send_from_directory('static', 'schedule.html')

@app.route('/api/schedule/<month_key>', methods=['GET'])
def get_schedule(month_key):
    data = load_data()
    if month_key not in data:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(data[month_key])

@app.route('/api/schedule/<month_key>/vote', methods=['POST'])
def vote(month_key):
    data = load_data()
    if month_key not in data:
        return jsonify({'error': 'Not found'}), 404

    body = request.get_json()
    name = body.get('name', '').strip()
    votes = body.get('votes', {})
    comment = body.get('comment', '').strip()

    if not name:
        return jsonify({'error': 'Name required'}), 400

    data[month_key]['votes'][name] = {
        'votes': votes,
        'comment': comment,
        'updated_at': datetime.now().isoformat()
    }
    save_data(data)
    return jsonify({'ok': True})

@app.route('/api/create-test', methods=['POST'])
def create_test():
    """テスト用：今月の日程調整を手動作成"""
    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"
    data = load_data()
    days = get_weekends_and_holidays(today.year, today.month)
    data[month_key] = {
        'year': today.year,
        'month': today.month,
        'days': days,
        'votes': {},
        'created_at': datetime.now().isoformat()
    }
    save_data(data)
    return jsonify({'ok': True, 'month_key': month_key, 'url': f"{BASE_URL}/schedule/{month_key}"})

@app.route('/api/send-test-line', methods=['POST'])
def send_test_line():
    """テスト用：LINEにメッセージを送信"""
    send_line_message("🤖 Botのテストメッセージです！正常に動作しています✅")
    return jsonify({'ok': True})

@app.route('/webhook', methods=['POST'])
def webhook():
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
