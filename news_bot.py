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
CACHE_META_FILE = os.path.join(STATE_DIR, "cache_meta.json")

os.makedirs(STATE_DIR, exist_ok=True)

def generate_filename():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"sent_articles_{timestamp}.json"

def get_cache_meta():
    """Получает метаданные о локальном кэше"""
    if os.path.exists(CACHE_META_FILE):
        try:
            with open(CACHE_META_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠ Ошибка при чтении метаданных кэша: {e}")
    return {"last_update": 0, "hash": ""}

def update_cache_meta(data):
    """Обновляет метаданные о локальном кэше"""
    meta = {
        "last_update": int(time.time()),
        "hash": hashlib.md5(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest(),
        "count": {
            "urls": len(data.get("urls", [])),
            "hashes": len(data.get("hashes", [])),
            "titles": len(data.get("titles", [])),
            "content_hashes": len(data.get("content_hashes", []))
        }
    }
    try:
        with open(CACHE_META_FILE, "w") as f:
            json.dump(meta, f, indent=2)
        print(f"📊 Метаданные кэша обновлены: {meta}")
        return meta
    except Exception as e:
        print(f"⚠ Ошибка при обновлении метаданных кэша: {e}")
        return None

def get_telegram_file_info():
    """Получает информацию о последнем файле из Telegram"""
    if not os.path.exists(STATE_FILE):
        return None
    
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠ Ошибка при чтении STATE_FILE: {e}")
        return None

def download_by_file_id(file_id, filename):
    try:
        info = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}").json()
        if not info.get("ok", False):
            print(f"⚠ Telegram API вернул ошибку: {info}")
            return None
            
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
    
    # Получаем метаданные о локальном кэше
    cache_meta = get_cache_meta()
    
    # Получаем информацию о файле в Telegram
    telegram_info = get_telegram_file_info()
    
    # Проверяем наличие локального кэша
    local_cache_exists = os.path.exists(LOCAL_CACHE_FILE)
    
    # Логика принятия решения о загрузке данных
    if telegram_info and telegram_info.get("file_id"):
        # Если есть информация о файле в Telegram, проверяем, нужно ли его скачивать
        need_download = True
        
        if local_cache_exists:
            # Если локальный кэш существует, проверяем его актуальность
            try:
                # Проверяем, когда был обновлен локальный кэш
                cache_mtime = os.path.getmtime(LOCAL_CACHE_FILE)
                state_mtime = os.path.getmtime(STATE_FILE)
                
                # Если STATE_FILE новее, чем локальный кэш, скачиваем файл
                if state_mtime <= cache_mtime:
                    need_download = False
                    print("📂 Локальный кэш актуален, используем его")
            except Exception as e:
                print(f"⚠ Ошибка при проверке времени модификации файлов: {e}")
        
        if need_download:
            print("🔄 Локальный кэш устарел или отсутствует, скачиваем файл из Telegram")
            path = download_by_file_id(telegram_info["file_id"], telegram_info.get("filename", filename))
            if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        loaded_data = json.load(f)
                    
                    # Обновляем структуру данных
                    data["urls"] = loaded_data.get("urls", [])
                    data["titles"] = loaded_data.get("titles", [])
                    data["hashes"] = loaded_data.get("hashes", [])
                    data["content_hashes"] = loaded_data.get("content_hashes", [])
                    
                    # Сохраняем в локальный кэш
                    save_local_cache(data)
                    return data, filename
                except Exception as e:
                    print(f"⚠ Ошибка при обработке загруженного файла: {e}")
    
    # Если не удалось загрузить из Telegram или не нужно скачивать, пробуем использовать локальный кэш
    if local_cache_exists:
        try:
            with open(LOCAL_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"📂 Загружен локальный кэш: {LOCAL_CACHE_FILE}")
            return data, filename
        except Exception as e:
            print(f"⚠ Ошибка при загрузке локального кэша: {e}")
    
    print("📭 Нет доступного файла для загрузки. Создаётся новый...")
    return data, filename

def save_local_cache(data):
    """Сохраняет данные в локальный кэш-файл"""
    try:
        with open(LOCAL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Локальный кэш обновлен: {LOCAL_CACHE_FILE}")
        
        # Обновляем метаданные кэша
        update_cache_meta(data)
        return True
    except Exception as e:
        print(f"⚠ Ошибка при сохранении локального кэша: {e}")
        return False

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
        if res.status_code == 200 and response_json.get("ok", False):
            if "result" in response_json and "document" in response_json["result"]:
                file_id = response_json["result"]["document"]["file_id"]
            else:
                file_id = response_json.get("document", {}).get("file_id")
        
        print("📌 Полученный file_id:", file_id)

        if res.status_code == 200 and file_id:
            with open(STATE_FILE, "w") as meta:
                json.dump({"file_id": file_id, "filename": local_file, "timestamp": int(time.time())}, meta)
            print(f"📤 Отправлен {local_file}, сохранён file_id")
            
            # Обновляем время модификации STATE_FILE, чтобы отразить факт обновления
            os.utime(STATE_FILE, None)
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

def clean_article_text(text):
    """Удаляет лишние фрагменты из текста статьи"""
    text = re.sub(r'^Titel:\s*', '', text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'Diese Nachricht wurde am .*? gesendet\.', '', text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()

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
    # Выводим информацию о состоянии файлов перед загрузкой
    if os.path.exists(LOCAL_CACHE_FILE):
        cache_mtime = datetime.fromtimestamp(os.path.getmtime(LOCAL_CACHE_FILE))
        print(f"📂 Локальный кэш существует, последнее изменение: {cache_mtime}")
    else:
        print("📂 Локальный кэш отсутствует")
        
    if os.path.exists(STATE_FILE):
        state_mtime = datetime.fromtimestamp(os.path.getmtime(STATE_FILE))
        print(f"📂 STATE_FILE существует, последнее изменение: {state_mtime}")
    else:
        print("📂 STATE_FILE отсутствует")
    
    # Загружаем историю отправленных статей
    sent, local_file = load_sent_articles()
    
    # Выводим информацию о загруженных данных
    print(f"📊 Загружено URLs: {len(sent.get('urls', []))}, Titles: {len(sent.get('titles', []))}, Hashes: {len(sent.get('hashes', []))}, Content Hashes: {len(sent.get('content_hashes', []))}")
    
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
            full_text = clean_article_text(full_text)

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
