import os
import json
import requests
from flask import Flask, request, jsonify, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, date
import calendar
import jpholiday

app = Flask(__name__, static_folder='static')

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_GROUP_ID = os.environ.get('LINE_GROUP_ID', '')
BASE_URL = os.environ.get('BASE_URL', 'https://your-app.onrender.com')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_SECRET_KEY = os.environ.get('SUPABASE_SECRET_KEY', '')

def sb_headers():
    return {
        'apikey': SUPABASE_SECRET_KEY,
        'Authorization': f'Bearer {SUPABASE_SECRET_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

def load_schedule(month_key):
    """Supabaseから指定月のデータを取得"""
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/schedules?month_key=eq.{month_key}",
        headers=sb_headers()
    )
    rows = res.json()
    if not rows:
        return None
    row = rows[0]
    return {
        'year': row['year'],
        'month': row['month'],
        'days': row['days'],
        'votes': row['votes'] or {}
    }

def save_schedule(month_key, year, month, days, votes):
    """Supabaseにデータを保存（upsert）"""
    payload = {
        'month_key': month_key,
        'year': year,
        'month': month,
        'days': days,
        'votes': votes
    }
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/schedules",
        headers={**sb_headers(), 'Prefer': 'resolution=merge-duplicates,return=representation'},
        json=payload
    )
    print(f"Supabase save: {res.status_code}")
    return res.status_code in [200, 201]

def update_votes(month_key, votes):
    """Supabaseの投票データだけ更新"""
    res = requests.patch(
        f"{SUPABASE_URL}/rest/v1/schedules?month_key=eq.{month_key}",
        headers=sb_headers(),
        json={'votes': votes}
    )
    print(f"Supabase update votes: {res.status_code}")

def get_weekends_and_holidays(year, month):
    days = []
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        for i, day in enumerate(week):
            if day == 0:
                continue
            d = date(year, month, day)
            is_weekend = i >= 5
            is_holiday = jpholiday.is_holiday(d)
            if is_weekend or is_holiday:
                days.append(d.strftime('%Y-%m-%d'))
    return days

def send_line_message(text):
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
    today = date.today()
    if today.month == 12:
        next_year, next_month = today.year + 1, 1
    else:
        next_year, next_month = today.year, today.month + 1

    month_key = f"{next_year}-{next_month:02d}"
    days = get_weekends_and_holidays(next_year, next_month)
    save_schedule(month_key, next_year, next_month, days, {})

    url = f"{BASE_URL}/schedule/{month_key}"
    month_name = f"{next_month}月"
    message = (
        f"🗓 {month_name}の日程調整を開始します！\n\n"
        f"土日祝の都合を教えてください⚾\n\n"
        f"📝 回答はこちら👇\n{url}\n\n"
        f"締め切り：今月の10日まで"
    )
    send_line_message(message)
    send_line_message("来月の野球できる日確認したいから、10日までに投票お願いします！")
    print(f"Created schedule for {month_key}")

def send_reminder():
    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"
    url = f"{BASE_URL}/schedule/{month_key}"
    message = (
        f"⚠️ 締め切りは明日なので投票してない人はよろしく！\n\n"
        f"📝 回答はこちら👇\n{url}"
    )
    send_line_message(message)

scheduler = BackgroundScheduler(timezone='Asia/Tokyo')
scheduler.add_job(create_schedule_for_next_month, 'cron', day=5, hour=9, minute=0)
scheduler.add_job(send_reminder, 'cron', day=9, hour=9, minute=0)
scheduler.start()

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/schedule/<month_key>')
def schedule_page(month_key):
    return send_from_directory('static', 'schedule.html')

@app.route('/api/schedule/<month_key>', methods=['GET'])
def get_schedule(month_key):
    data = load_schedule(month_key)
    if not data:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(data)

@app.route('/api/schedule/<month_key>/vote', methods=['POST'])
def vote(month_key):
    data = load_schedule(month_key)
    if not data:
        return jsonify({'error': 'Not found'}), 404

    body = request.get_json()
    name = body.get('name', '').strip()
    votes = body.get('votes', {})
    notes = body.get('notes', {})

    if not name:
        return jsonify({'error': 'Name required'}), 400

    data['votes'][name] = {
        'votes': votes,
        'notes': notes,
        'updated_at': datetime.now().isoformat()
    }
    update_votes(month_key, data['votes'])
    return jsonify({'ok': True})

@app.route('/api/create-test', methods=['POST'])
def create_test():
    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"
    days = get_weekends_and_holidays(today.year, today.month)
    save_schedule(month_key, today.year, today.month, days, {})
    return jsonify({'ok': True, 'month_key': month_key, 'url': f"{BASE_URL}/schedule/{month_key}"})

@app.route('/api/send-test-line', methods=['POST'])
def send_test_line():
    send_line_message("🤖 Botのテストメッセージです！正常に動作しています✅")
    return jsonify({'ok': True})

@app.route('/api/test-schedule-message', methods=['POST'])
def test_schedule_message():
    create_schedule_for_next_month()
    return jsonify({'ok': True})

@app.route('/api/test-reminder-message', methods=['POST'])
def test_reminder_message():
    send_reminder()
    return jsonify({'ok': True})

@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_json()
    print(f"Webhook received: {json.dumps(body, ensure_ascii=False)}")
    if body and 'events' in body:
        for event in body['events']:
            source = event.get('source', {})
            group_id = source.get('groupId')
            if group_id:
                print(f"GROUP ID: {group_id}")
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
