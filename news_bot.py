# -*- coding: utf-8 -*-
import os
import sys
import time
import json
# Загружаем отправленные статьи
sent_data = {"urls": [], "hashes": []}
try:
    with open("sent_articles.json", "r", encoding="utf-8") as f:
        sent_data = json.load(f)
except Exception:
    pass

def is_duplicate(url, text):
    from hashlib import md5
    text_hash = md5(text[:1000].encode("utf-8")).hexdigest()
    return url in sent_data["urls"] or text_hash in sent_data["hashes"]

def remember_article(url, text):
    from hashlib import md5
    text_hash = md5(text[:1000].encode("utf-8")).hexdigest()
    sent_data["urls"].append(url)
    sent_data["hashes"].append(text_hash)
    # Оставляем только последние 1000 записей
    sent_data["urls"] = sent_data["urls"][-1000:]
    sent_data["hashes"] = sent_data["hashes"][-1000:]
    with open("sent_articles.json", "w", encoding="utf-8") as f:
        json.dump(sent_data, f)

import feedparser
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from readability import Document
from bs4 import BeautifulSoup

load_dotenv()
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SOURCES = [
    "https://www.spiegel.de/international/index.rss",
    "https://www.zdf.de/rss/zdfheutea.xml",
    "https://www.faz.net/rss/aktuell/"
]

SENT_ARTICLES_FILE = "sent_articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def load_sent_articles():
    if os.path.exists(SENT_ARTICLES_FILE):
        try:
            with open(SENT_ARTICLES_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as e:
            print("Fehler beim Laden von sent_articles.json:", e)
    return {"urls": []}

def save_sent_articles(data):
    try:
        with open(SENT_ARTICLES_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Fehler beim Speichern von sent_articles.json:", e)

def is_recent(entry):
    try:
        published = entry.get("published_parsed")
        if not published:
            return False
        published_dt = datetime(*published[:6])
        return published_dt > datetime.utcnow() - timedelta(hours=3)
    except:
        return False

def fetch_articles():
    articles = []
    for feed_url in SOURCES:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            if not is_recent(entry):
                continue
            link = entry.link
            title = entry.title
            published = entry.get("published", "")
            articles.append({"title": title, "link": link, "published": published})
    return articles

def extract_full_text(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        doc = Document(response.text)
        html = doc.summary()
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text()
    except Exception as e:
        print("❌ Fehler beim Extrahieren:", e)
        return ""

def extract_image_url(url):
    try:
        html = requests.get(url, headers=HEADERS, timeout=5).text
        soup = BeautifulSoup(html, "html.parser")
        og_image = soup.find("meta", property="og:image")
        if og_image:
            return og_image.get("content")
    except:
        return None




def summarize(text):
    prompt = (
        "Fasse diesen deutschen Nachrichtentext in 4–7 Sätzen zusammen. "
        "Verfasse zuerst einen spannenden, aber sachlichen Titel (ohne Anführungszeichen), dann einen stilistisch ansprechenden Nachrichtentext. "
        "Nutze kurze Absätze und formuliere professionell und klar." + text
    )
    
    try:
        response = client.chat.completions.create(
            model="mistralai/mistral-7b-instruct",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Fehler bei OpenRouter:", e)
        return None


def send_to_telegram(text, image_url=None):
    url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    url_text = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "caption": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        if image_url:
            payload["photo"] = image_url
            requests.post(url_photo, data=payload)
        else:
            payload["text"] = text
            del payload["caption"]
            requests.post(url_text, data=payload)
    except Exception as e:
        print("Fehler bei Telegram:", e)

def send_log_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("❌ Fehler beim Senden des Logs:", e)

def format_summary(summary, link):
    return summary + f"\n\n[Weiterlesen]({link})"

def main_loop(debug=False):
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
    send_log_to_telegram(f"🟢 Bot gestartet – {now}")

    print("\n⏳ Überprüfe RSS-Feeds...")
    articles = fetch_articles()
    sent_data = load_sent_articles()
    count = 0

    for article in articles:
        if article["link"] in sent_data["urls"]:
            continue

        print(f"🔎 Analysiere: {article['title']}")
        print(f"🔗 {article['link']}")

        full_text = extract_full_text(article["link"])
        print("📄 Textauszug:", full_text[:300])
        print("📏 Länge:", len(full_text))

        if not full_text or len(full_text) < 100:
            print("❌ Zu wenig Text oder Fehler beim Extrahieren")
            continue

        summary = summarize(full_text)
        if summary:
            image_url = extract_image_url(article["link"])
            formatted = format_summary(summary, article["link"])
            send_to_telegram(formatted, image_url=image_url)
            print("✅ Gesendet")

            sent_data["urls"].append(article["link"])
            save_sent_articles(sent_data)
            count += 1
            time.sleep(5)

    if count == 0:
        send_log_to_telegram("⚠️ Keine neuen Artikel gefunden.")
    else:
        send_log_to_telegram(f"✅ {count} neue Artikel gesendet.")

if __name__ == "__main__":
    main_loop(debug=True)
