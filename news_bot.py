import os
import json
import time
import hashlib
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
from readability import Document

# --- Константы ---
FEEDS = [
    "https://www.spiegel.de/international/index.rss",
    "https://www.zdf.de/rss/zdfheutea.xml",
    "https://www.faz.net/rss/aktuell/"
]

MAX_ARTICLES = 1000  # сколько храним статей в списке
MAX_TOKENS = 800     # лимит модели
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CHAT_ID = os.getenv("CHAT_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}

def load_sent_articles():
    try:
        with open("sent_articles.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"urls": [], "hashes": []}

def save_sent_articles(data):
    data["urls"] = data["urls"][-MAX_ARTICLES:]
    data["hashes"] = data["hashes"][-MAX_ARTICLES:]
    with open("sent_articles.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_article_text(url):
    try:
        response = requests.get(url, timeout=10)
        html = response.text
        doc = Document(html)
        summary = doc.summary()
        text = BeautifulSoup(summary, "html.parser").get_text(separator=" ", strip=True)
        if len(text) < 100:
            # fallback
            soup = BeautifulSoup(html, "html.parser")
            article = soup.find("article") or soup.find("main")
            if article:
                text = " ".join([p.get_text(strip=True) for p in article.find_all("p")])
            else:
                text = " ".join([p.get_text(strip=True) for p in soup.find_all("p")])
        return text.strip()
    except Exception as e:
        print(f"⚠ Fehler beim Abrufen des Artikels: {e}")
        return ""

def summarize(text):
    prompt = f'''
Fasse diesen deutschen Nachrichtentext in 4-7 Sätzen zusammen. Verfasse zuerst einen spannenden, aber sachlichen Titel (ohne Anführungszeichen), dann einen stilistisch ansprechenden Nachrichtentext. Nutze kurze Absätze und formuliere professionell und klar.

Danach übersetze denselben Text vollständig auf Russisch.

Text: {text}
'''

    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=HEADERS, json={
            "model": "mistralai/mistral-7b-instruct:free",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": MAX_TOKENS
        }, timeout=60)

        res.raise_for_status()
        data = res.json()
        return data["choices"][0]["message"]["content"]
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
    res = requests.post(url, json=payload)
    return res.status_code == 200

def main():
    sent = load_sent_articles()
    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            url = entry.link
            if url in sent["urls"]:
                continue

            title = entry.title
            full_text = get_article_text(url)
            if len(full_text) < 200:
                print(f"⚠ Übersprungen ({feed_url}): {title} (zu kurz)")
                continue

            hash_ = hashlib.md5(full_text.encode("utf-8")).hexdigest()
            if hash_ in sent["hashes"]:
                continue

            print(f"🔄 Analysiere: {title}")
            summary = summarize(full_text)
            if not summary:
                continue

            message = f"<b>📰 {title}</b>\n\n{summary}\n\n🔗 <a href='{url}'>Quelle öffnen</a>"
            success = send_message(message)
            if success:
                print("✅ Gesendet")
                sent["urls"].append(url)
                sent["hashes"].append(hash_)
            else:
                print("⚠ Fehler beim Senden")

    save_sent_articles(sent)

if __name__ == "__main__":
    main()