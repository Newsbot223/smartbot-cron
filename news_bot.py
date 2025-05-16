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
MAX_AGE_SECONDS = 21600 # 6 часов

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
    "wetter", "wetterbericht", "regen", "sonnig", "heiter", "unwetter",
    "vorhersage", "temperature", "schnee", "hitze",
    "sport", "bundesliga", "fußball", "tor", "spiel", "trainer",
    "verein", "tabelle", "champions league", "olympia", "weltmeisterschaft",
    "spieltag", "tennis", "formel 1", "handball", "basketball"
]

STATE_DIR = "bot-state"
STATE_FILE = os.path.join(STATE_DIR, "last_file_id.json")
LOCAL_CACHE_FILE = os.path.join(STATE_DIR, "local_cache.json")

os.makedirs(STATE_DIR, exist_ok=True)

def generate_filename():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"sent_articles_{timestamp}.json"

def download_by_file_id(file_id, filename):
    try:
        info = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}").json()
        file_path = info["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        data = requests.get(url).content
        with open(filename, "wb") as f:
            f.write(data)
        print(f"📥 Успешно загружен {filename} из Telegram по file_id")
        return filename
    except Exception as e:
        print("⚠ Ошибка при скачивании по file_id:", e)
        return None

def load_sent_articles():
    data = {"urls": [], "content_hashes": [], "titles": [], "hashes": []}
    filename = generate_filename()
    
    # Сначала пробуем загрузить локальный кэш
    if os.path.exists(LOCAL_CACHE_FILE):
        try:
            with open(LOCAL_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"📂 Загружен локальный кэш: {LOCAL_CACHE_FILE}")
            return data, filename
        except Exception as e:
            print(f"⚠ Ошибка при загрузке локального кэша: {e}")
    
    # Если локальный кэш не доступен, пробуем загрузить из Telegram
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                obj = json.load(f)
                file_id = obj.get("file_id")
                filename = obj.get("filename")
            
            if file_id and filename:
                print("📂 Пробуем скачать по сохранённому file_id...")
                path = download_by_file_id(file_id, filename)
                if path and os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            loaded_data = json.load(f)
                        
                        # Обновляем структуру данных, если нужно
                        data["urls"] = loaded_data.get("urls", [])
                        data["titles"] = loaded_data.get("titles", [])
                        data["hashes"] = loaded_data.get("hashes", [])
                        
                        # Добавляем новое поле для хешей содержимого, если его нет
                        if "content_hashes" not in loaded_data:
                            data["content_hashes"] = []
                        else:
                            data["content_hashes"] = loaded_data["content_hashes"]
                        
                        # Сохраняем в локальный кэш
                        save_local_cache(data)
                        return data, filename
                    except Exception as e:
                        print(f"⚠ Ошибка при обработке загруженного файла: {e}")
        except Exception as e:
            print(f"⚠ Ошибка при чтении STATE_FILE: {e}")
    
    print("📭 Нет доступного файла для загрузки. Создаётся новый...")
    return data, filename

def save_local_cache(data):
    """Сохраняет данные в локальный кэш-файл"""
    try:
        with open(LOCAL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Локальный кэш обновлен: {LOCAL_CACHE_FILE}")
    except Exception as e:
        print(f"⚠ Ошибка при сохранении локального кэша: {e}")

def save_sent_articles(data, local_file):
    # Ограничиваем размер списков
    data["urls"] = data["urls"][-MAX_ARTICLES:]
    data["hashes"] = data["hashes"][-MAX_ARTICLES:]
    data["titles"] = data.get("titles", [])[-MAX_ARTICLES:]
    data["content_hashes"] = data.get("content_hashes", [])[-MAX_ARTICLES:]
    
    # Сохраняем в локальный кэш
    save_local_cache(data)
    
    # Сохраняем в файл для отправки
    with open(local_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(local_file, "rb") as f:
        files = {"document": f}
        data_tg = {"chat_id": CHAT_ID, "caption": "✅ Новый sent_articles файл"}
        res = requests.post(url, files=files, data=data_tg)

        try:
            response_json = res.json()
            print("📦 Ответ Telegram:", json.dumps(response_json, indent=2))
        except Exception as e:
            print("⚠ Не удалось распарсить JSON-ответ Telegram:", e)
            response_json = {}

        file_id = None
        if res.status_code == 200:
            if "result" in response_json and "document" in response_json["result"]:
                file_id = response_json["result"]["document"]["file_id"]
            else:
                file_id = response_json.get("document", {}).get("file_id")
        
        print("📌 Полученный file_id:", file_id)

        if res.status_code == 200 and file_id:
            with open(STATE_FILE, "w") as meta:
                json.dump({"file_id": file_id, "filename": local_file}, meta)
            print(f"📤 Отправлен {local_file}, сохранён file_id")
        else:
            print(f"⚠ Ошибка при отправке файла: {res.status_code}")

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

def normalize_text(text):
    """Нормализует текст для более надежного сравнения"""
    if not text:
        return ""
    # Удаляем все пробельные символы и приводим к нижнему регистру
    text = re.sub(r'\s+', ' ', text.lower()).strip()
    # Удаляем пунктуацию
    text = re.sub(r'[^\w\s]', '', text)
    return text

def get_content_hash(text):
    """Создает хеш только от содержимого статьи"""
    # Берем больше текста для более надежного хеша
    normalized_text = normalize_text(text[:1000])
    return hashlib.md5(normalized_text.encode("utf-8")).hexdigest()

def is_duplicate_content(text, sent_data):
    """Проверяет, является ли статья дубликатом по содержанию"""
    if not text:
        return False
    
    # Создаем хеш от содержимого
    content_hash = get_content_hash(text)
    
    # Проверяем, есть ли такой хеш в истории
    if content_hash in sent_data.get("content_hashes", []):
        print("🔄 Дубликат содержимого обнаружен по хешу содержания")
        return True
    
    # Дополнительная проверка на схожесть текста (для случаев небольших изменений)
    normalized_text = normalize_text(text[:500])
    for i, old_hash in enumerate(sent_data.get("content_hashes", [])):
        # Если у нас есть сохраненный текст, можно было бы сравнить напрямую
        # Но так как у нас только хеши, используем дополнительную проверку по старому алгоритму
        if i < len(sent_data.get("hashes", [])):
            old_hash_base = sent_data.get("hashes", [])[i]
            if old_hash_base and normalized_text and old_hash_base.startswith(normalized_text[:20]):
                print("🔄 Дубликат содержимого обнаружен по частичному совпадению")
                return True
    
    return False

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
            return result["choices"][0]["message"]["content"].strip()
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

def main():
    sent, local_file = load_sent_articles()
    
    # Убедимся, что у нас есть все необходимые ключи
    if "content_hashes" not in sent:
        sent["content_hashes"] = []

    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            url = entry.link
            title = entry.title

            # Базовая проверка по URL и заголовку
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

            if len(full_text) > MAX_CHARS:
                print(f"⚠ Zu lang, übersprungen: {title} ({len(full_text)} Zeichen)")
                continue

            if len(full_text) < 200:
                print(f"⚠ Übersprungen ({feed_url}): {title} (zu kurz)")
                continue

            # Проверка на релевантность и блокировку по ключевым словам
            if not any(keyword.lower() in full_text.lower() for keyword in KEYWORDS):
                print(f"⛔ Thema nicht relevant: {title}")
                continue

            if any(word in full_text.lower() for word in BLOCKED_KEYWORDS):
                print(f"❌ Thema blockiert: {title}")
                continue

            # Проверка на дубликаты по содержимому
            if is_duplicate_content(full_text, sent):
                print(f"🔄 Дубликат содержимого: {title}")
                continue

            # Старый метод хеширования для обратной совместимости
            hash_base = (title + full_text[:300].lower()).strip()
            hash_ = hashlib.md5(hash_base.encode("utf-8")).hexdigest()
            if hash_ in sent["hashes"]:
                print(f"🔄 Дубликат по старому хешу: {title}")
                continue

            # Новый метод хеширования только содержимого
            content_hash = get_content_hash(full_text)

            print(f"🔄 Analysiere: {title}")
            summary = summarize(full_text)
            if not summary:
                continue

            caption = f"<b>📰 {title}</b>\n\n{summary}\n\n🔗 <a href='{url}'>Weiterlesen</a>"

            success = send_message(caption)
            if success:
                print("✅ Gesendet")
                sent["urls"].append(url)
                sent["hashes"].append(hash_)
                sent["content_hashes"].append(content_hash)
                if title not in sent["titles"]:
                    sent["titles"].append(title)
                
                # Сохраняем локальный кэш после каждой успешной отправки
                save_local_cache(sent)
            else:
                print("⚠ Fehler beim Senden")

    save_sent_articles(sent, local_file)

if __name__ == "__main__":
    main()
