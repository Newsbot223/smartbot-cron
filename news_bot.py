import os
import json
import time
import hashlib
import requests
import feedparser
import re
from bs4 import BeautifulSoup
from datetime import datetime
from readability import Document

# --- Константы ---
FEEDS = [
    "https://www.deutschlandfunk.de/nachrichten-100.rss",
    "https://www.deutschlandfunk.de/politikportal-100.rss",
    "https://www.deutschlandfunk.de/wirtschaft-106.rss",
    "https://www.spiegel.de/thema/deutschland/index.rss",
    "https://www.faz.net/rss/aktuell/politik/inland"
]

MAX_ARTICLES = 1000
MAX_TOKENS = 800
MAX_CHARS = 8000
MAX_AGE_SECONDS = 43200  # 12 часов

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CHAT_ID = os.getenv("CHAT_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}

KEYWORDS = [
    "regierung", "bundestag", "wirtschaft", "ampel", "haushalt", "migration",
    "bürgergeld", "afd", "spd", "cdu", "grüne", "wahl", "streik",
    "arbeitsmarkt", "deutschland", "eu", "gesetz", "energie", "asyl", "krieg",
    "grenze", "grenzen", "grenzschutz", "bundespolizei", "flüchtlinge", "einreise"
]

BLOCKED_KEYWORDS = [
    # Погода
    "wetter", "wetterbericht", "regen", "sonnig", "heiter", "unwetter",
    "vorhersage", "temperature", "schnee", "hitze",

    # Спорт
    "sport", "bundesliga", "fußball", "tor", "spiel", "trainer",
    "verein", "tabelle", "champions league", "olympia", "weltmeisterschaft",
    "spieltag", "tennis", "formel 1", "handball", "basketball"
]

def load_sent_articles():
    try:
        with open("sent_articles.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            print("📂 Загружено из JSON:", json.dumps(data, indent=2, ensure_ascii=False))
            return data
    except:
        return {"urls": [], "hashes": [], "titles": []}

    upload_sent_json()
    data["hashes"] = data["hashes"][-MAX_ARTICLES:]
    data["titles"] = data.get("titles", [])[-MAX_ARTICLES:]
    with open("sent_articles.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def summarize(text):
    prompt = f'''
Fasse diesen deutschen Nachrichtentext in 4–7 Sätzen zusammen. Verfasse zuerst einen spannenden, aber sachlichen Titel (ohne Anführungszeichen), dann einen stilistisch ansprechenden Nachrichtentext. Nutze kurze Absätze und formuliere professionell und klar.

Text: {text}
'''
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=HEADERS, json={
            "model": "mistralai/mistral-7b-instruct",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": MAX_TOKENS
        }, timeout=60)

        res.raise_for_status()
        result = res.json()
        if "choices" in result and isinstance(result["choices"], list):
            full = result["choices"][0]["message"]["content"].strip()
            lines = full.splitlines()
            cleaned = "".join([
                line for line in lines
                if not any(line.strip().lower().startswith(x) for x in ("title:", "titel:", "text:"))
            ])
            summary = cleaned.strip()
            if summary.count(".") > 7:
                summary = ".".join(summary.split(".")[:7]) + "."
            return summary
    except Exception as e:
        print("Fehler bei Zusammenfassung:", e)
        return ""

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    return requests.post(url, json=payload).status_code == 200

    
def get_latest_sent_file_id():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url).json()
        for update in reversed(res["result"]):
            doc = update.get("message", {}).get("document", {})
            if doc.get("file_name") == "sent_articles.json":
                return doc.get("file_id")
    except Exception as e:
        print("⚠ Fehler bei getUpdates:", e)
    return None

def download_sent_json():
    file_id = get_latest_sent_file_id()
    if not file_id:
        print("❗ Не найден файл sent_articles.json в getUpdates.")
        return
    info = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}").json()
    file_path = info["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    data = requests.get(url).content
    with open("sent_articles.json", "wb") as f:
        f.write(data)
    print("📥 Загружен самый свежий sent_articles.json из Telegram")

    with open("sent_articles.json", "rb") as f:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        files = {"document": f}
        data = {"chat_id": CHAT_ID, "caption": "✅ Обновлённый sent_articles.json"}
        response = requests.post(url, files=files, data=data)
        print("📤 Отправлен sent_articles.json в Telegram:", response.status_code)

def get_article_text(url):
    try:
        response = requests.get(url, timeout=10)
        html = response.text
        doc = Document(html)
        summary = doc.summary()
        text = BeautifulSoup(summary, "html.parser").get_text(separator="\n", strip=True)
        return text
    except Exception as e:
        print("⚠ Ошибка при загрузке статьи:", e)
        return ""

        response = requests.get(url, timeout=10)
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    except Exception as e:
        print("⚠ Ошибка при получении изображения:", e)
    return None

def save_sent_articles(data):
    data["urls"] = data["urls"][-MAX_ARTICLES:]
    data["hashes"] = data["hashes"][-MAX_ARTICLES:]
    data["titles"] = data.get("titles", [])[-MAX_ARTICLES:]

    if not data['urls'] or not data['hashes']:
        print("⚠️ Нет новых данных — файл не пересылается.")
        return

    with open("sent_articles.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("💾 sent_articles.json сохранён.")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open("sent_articles.json", "rb") as f:
        response = requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})
        print("📤 Отправка файла в Telegram... статус:", response.status_code)
        print("📨 Ответ Telegram:", response.text)

def main():
    if not os.path.exists("sent_articles.json"):
        download_sent_json()
    else:
        print("📁 Используется локальный sent_articles.json (не скачиваем)")
    sent = load_sent_articles()
    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            url = entry.link

            title = entry.title
            if url in sent["urls"] or title in sent["titles"]:
                print(f"⏩ Bereits verarbeitet: {title}")
                continue

            published = entry.get("published_parsed")
            if published:
                pub_date = datetime.fromtimestamp(time.mktime(published))
                if (datetime.utcnow() - pub_date).total_seconds() > MAX_AGE_SECONDS:
                    print(f"⏳ Zu alt, übersprungen: {title}")
                    continue

            full_text = get_article_text(url)

            UNWANTED_ENDINGS = [
                r'Diese Entwicklung wurde am \d{2}\.\d{2}\.\d{4} .*? berichtet\.',
                r'Diese Meldung wurde am \d{2}\.\d{2}\.\d{4} .*? veröffentlicht\.',
                r'Diese Nachricht wurde am \d{2}\.\d{2}\.\d{4} .*? veröffentlicht\.',
                r'Die Nachricht wurde am gleichen Tag veröffentlicht\.',
                r'Die Information wurde am selben Tag verbreitet\.',
                r'Die Verbreitung dieser Flyer wurde am .*? gemeldet\.',
                r'Der Link zur Nachricht kann.*?(kopiert|geteilt).*?',
                r'Am \d{2}\.\d{2}\.\d{4} veröffentlicht\.',
                r'(Veröffentlicht|Berichtet) am \d{2}\.\d{2}\.\d{4}',
                r'\(?Stand: \d{2}\.\d{2}\.\d{4}\)?',
                r'\(?\d{2}\.\d{2}\.\d{4}\)?\s*im Programm Deutschlandfunk'
            ]

            for pattern in UNWANTED_ENDINGS:
                full_text = re.sub(pattern, '', full_text, flags=re.IGNORECASE)

            

            if len(full_text) > MAX_CHARS:
                print(f"⚠ Zu lang, übersprungen: {title} ({len(full_text)} Zeichen)")
                continue

            if len(full_text) < 200:
                print(f"⚠ Übersprungen ({feed_url}): {title} (zu kurz)")
                continue

            if not any(keyword.lower() in full_text.lower() for keyword in KEYWORDS):
                print(f"⛔ Thema nicht relevant: {title}")
                continue

            if any(word in full_text.lower() for word in BLOCKED_KEYWORDS):
                print(f"❌ Thema blockiert: {title}")
                continue

            hash_base = (title + full_text[:300].lower()).strip()
            hash_ = hashlib.md5(hash_base.encode("utf-8")).hexdigest()
            if hash_ in sent["hashes"]:
                continue

            print(f"🔄 Analysiere: {title}")
            summary = summarize(full_text)
            if not summary:
                continue      

            caption = f"<b>📰 {title}</b>\n\n{summary}\n\n🔗 <a href='{url}'>Weiterlesen</a>"

            success = False
            success = send_message(caption)

            if success:
                print("✅ Gesendet")
                sent["urls"].append(url)
                sent["hashes"].append(hash_)
                sent["titles"].append(title)
            else:
                print("⚠ Fehler beim Senden")

    print("💾 Сохраняем данные:", json.dumps(sent, indent=2, ensure_ascii=False))
    save_sent_articles(sent)

if __name__ == "__main__":
    main()

def save_sent_articles(data):
    data["urls"] = data["urls"][-MAX_ARTICLES:]
    data["hashes"] = data["hashes"][-MAX_ARTICLES:]
    data["titles"] = data.get("titles", [])[-MAX_ARTICLES:]

    print("📊 URLs:", data["urls"])
    print("📊 Hashes:", data["hashes"])
    print("📊 Titles:", data["titles"])

    if not data['urls'] or not data['hashes']:
        print("⚠️ Нет новых данных — файл не пересылается.")
        return

    with open("sent_articles.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("💾 sent_articles.json сохранён.")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open("sent_articles.json", "rb") as f:
        response = requests.post(url, data={"chat_id": CHAT_ID}, files={"document": f})
        print("📤 Отправка в Telegram... статус:", response.status_code)
        print("📨 Ответ Telegram:", response.text)