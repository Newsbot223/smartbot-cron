# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import feedparser
import requests
import openai
from datetime import datetime, timedelta
from dotenv import load_dotenv
from readability import Document
from bs4 import BeautifulSoup

load_dotenv()
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

openai.api_key = os.getenv("OPENAI_API_KEY")

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SOURCES = [
    "https://www.spiegel.de/international/index.rss",
    "https://www.zdf.de/rss/zdfheutea.xml",
    "https://www.faz.net/rss/aktuell/",
    "https://www.belltower.news/feed/",
    "https://overton-magazin.de/feed/"
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
        "Nutze kurze Absätze und formuliere professionell und klar:\n\n"
        f"{text}"
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Du bist Nachrichtenredakteur und schreibst klar, sachlich und ansprechend für Telegram."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("Fehler bei OpenAI:", e)
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
    print(f"🔗 {article['link']}")  # Показывает ссылку

    full_text = extract_full_text(article["link"])
    print("📄 Textauszug:", full_text[:300])  # Показывает первые 300 символов
    print("📏 Länge:", len(full_text))         # Показывает длину текста

    if not full_text or len(full_text) < 100:  # Временно снижаем порог
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
