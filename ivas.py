import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime
import re
from bs4 import BeautifulSoup
import os
import asyncio
import json
import pycountry
import time
from threading import Lock
import signal
import ssl
from urllib3.util.ssl_ import create_urllib3_context
import html
ssl._create_default_https_context = ssl._create_unverified_context
try:
    import brotlicffi as brotli
except ImportError:
    try:
        import brotli
    except ImportError:
        brotli = None

BOT_TOKEN = "8499568371:AAEtrOMVYcoYHYWVgeViPerpWdn0SDrbQjs"
CHAT_IDS = ["-1002796548432"]
TIMEOUT = (15, 45)
MAX_RETRIES = 3
MAX_BATCH_SIZE = 20
BATCH_DELAY = 3

ctx = create_urllib3_context()
ctx.load_default_certs()
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(
    max_retries=MAX_RETRIES,
    pool_connections=10,
    pool_maxsize=100
)
session.mount("https://", adapter)
session.verify = False

LOGIN_URL = "https://www.ivasms.com/login"
SMS_LIST_URL = "https://www.ivasms.com/portal/sms/received/getsms"
SMS_NUMBERS_URL = "https://www.ivasms.com/portal/sms/received/getsms/number"
SMS_DETAILS_URL = "https://www.ivasms.com/portal/sms/received/getsms/number/sms"

EMAIL = "modviprm@gmail.com"
PASSWORD = "Ruhul@1@"

MAX_LOGIN_ATTEMPTS = 3
RETRY_DELAY = 10
SESSION_REFRESH_INTERVAL = 1800
OTP_HISTORY_FILE = "otp_history.json"
OTP_DUPLICATE_WINDOW = 60
SMS_CACHE_FILE = "sms_cache.json"

file_lock = Lock()

COUNTRY_ALIASES = {
    "IVORY": "Côte d'Ivoire",
    "USA": "United States", 
    "UK": "United Kingdom",
    "UAE": "United Arab Emirates",
    "BOLIVIA": "Bolivia"
}

def get_flag_emoji(country_code):
    try:
        if not country_code or len(country_code) != 2:
            return "🌍"
        code_points = [ord(c.upper()) - ord('A') + 0x1F1E6 for c in country_code]
        return chr(code_points[0]) + chr(code_points[1])
    except Exception:
        return "🌍"

def get_country_emoji(country_name):
    try:
        country_name = COUNTRY_ALIASES.get(country_name.upper(), country_name)
        countries = pycountry.countries.search_fuzzy(country_name)
        if countries:
            return get_flag_emoji(countries[0].alpha_2)
        return "🌍"
    except Exception:
        return "🌍"

SMS_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.ivasms.com/portal/sms/received",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "text/html, */*; q=0.01",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Accept-Encoding": "gzip, deflate"
}

SERVICE_PATTERNS = {
    "WhatsApp": r"(whatsapp|wa\.me|verify|wassap|whtsapp)",
    "Facebook": r"(facebook|fb\.me|fb\-|meta)",
    "Telegram": r"(telegram|t\.me|tg|telegrambot)",
    "Google": r"(google|gmail|goog|g\.co|accounts\.google)",
    "Twitter": r"(twitter|x\.com|twtr)",
    "Instagram": r"(instagram|insta|ig)",
    "Lalamove": r"(lalamove)",
    "Apple": r"(apple|icloud|appleid)",
    "Snapchat": r"(snapchat|snap)",
    "TikTok": r"(tiktok|musically)",
    "LinkedIn": r"(linkedin|lnkd)",
    "Discord": r"(discord)",
    "Uber": r"(uber)",
    "Netflix": r"(netflix)",
    "Amazon": r"(amazon|aws)",
    "Microsoft": r"(microsoft|outlook|hotmail)",
    "PayPal": r"(paypal)",
    "Spotify": r"(spotify)"
}

def load_sms_cache():
    with file_lock:
        try:
            if os.path.exists(SMS_CACHE_FILE):
                with open(SMS_CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading SMS cache: {e}")
            return {}

def save_sms_cache(cache):
    with file_lock:
        try:
            with open(SMS_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, indent=4)
        except Exception as e:
            print(f"Error saving SMS cache: {e}")

def load_otp_history():
    with file_lock:
        try:
            if os.path.exists(OTP_HISTORY_FILE):
                with open(OTP_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading OTP history: {e}")
            return {}

def save_otp_history(history):
    with file_lock:
        try:
            with open(OTP_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4)
        except Exception as e:
            print(f"Error saving OTP history: {e}")

def check_and_save_otp(number, otp, message_id):
    if otp == "No OTP found":
        return True
        
    history = load_otp_history()
    current_time = datetime.now().isoformat()
    
    if number not in history:
        history[number] = [{"otp": otp, "message_id": message_id, "timestamp": current_time}]
        save_otp_history(history)
        return True
    
    for entry in history[number]:
        if entry["otp"] == otp and entry["message_id"] != message_id:
            entry_time = datetime.fromisoformat(entry["timestamp"])
            if (datetime.now() - entry_time).total_seconds() < OTP_DUPLICATE_WINDOW:
                return False
    
    history[number].append({"otp": otp, "message_id": message_id, "timestamp": current_time})
    save_otp_history(history)
    return True

def format_otp_with_spaces(otp):
    if otp == "No OTP found":
        return otp
    otp_clean = re.sub(r'[^\d]', '', otp)
    if len(otp_clean) >= 4:
        return " ".join(otp_clean)
    return otp

async def get_csrf_token():
    try:
        print("🔄 Getting CSRF token...")
        response = session.get(LOGIN_URL, timeout=TIMEOUT)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        csrf_input = soup.find('input', {'name': '_token'})
        
        if csrf_input is None:
            print("❌ CSRF token input not found in login page")
            return None
            
        csrf_token = csrf_input.get('value')
        if not csrf_token:
            print("❌ CSRF token value is empty")
            return None
            
        print(f"✅ CSRF token obtained: {csrf_token[:20]}...")
        return csrf_token
    except Exception as e:
        print(f"❌ Error getting CSRF token: {e}")
        return None

async def login(attempt=1):
    if attempt > MAX_LOGIN_ATTEMPTS:
        print(f"❌ Login failed after {MAX_LOGIN_ATTEMPTS} attempts")
        return False
        
    try:
        print(f"🔐 Attempting login (attempt {attempt}/{MAX_LOGIN_ATTEMPTS})...")
        
        csrf_token = await get_csrf_token()
        if not csrf_token:
            print(f"❌ Failed to get CSRF token on attempt {attempt}")
            await asyncio.sleep(RETRY_DELAY)
            return await login(attempt + 1)
        
        login_data = {
            "_token": csrf_token,
            "email": EMAIL,
            "password": PASSWORD
        }
        
        print("📡 Sending login request...")
        login_response = session.post(LOGIN_URL, data=login_data, timeout=TIMEOUT)
        login_response.raise_for_status()
        
        if "dashboard" in login_response.url or "portal" in login_response.url:
            print(f"✅ Login successful on attempt {attempt}")
            return True
        else:
            print(f"❌ Login failed on attempt {attempt} - unexpected redirect: {login_response.url}")
            await asyncio.sleep(RETRY_DELAY)
            return await login(attempt + 1)
            
    except Exception as e:
        print(f"❌ Login error on attempt {attempt}: {e}")
        await asyncio.sleep(RETRY_DELAY)
        return await login(attempt + 1)

async def refresh_session(last_login_time):
    current_time = time.time()
    if current_time - last_login_time >= SESSION_REFRESH_INTERVAL:
        print("🔄 Refreshing session...")
        if await login():
            print("✅ Session refreshed successfully")
            return True, current_time
        else:
            print("❌ Session refresh failed")
            return False, last_login_time
    return True, last_login_time

def decode_response(response):
    try:
        content_encoding = response.headers.get('Content-Encoding', '')
        if content_encoding == 'br' and brotli:
            try:
                return brotli.decompress(response.content).decode('utf-8')
            except Exception:
                pass
        
        try:
            return response.text
        except Exception:
            return response.content.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"❌ Error decoding response: {e}")
        try:
            return response.content.decode('utf-8', errors='ignore')
        except:
            return str(response.content)

async def fetch_sms():
    try:
        print("📱 Fetching SMS ranges...")
        csrf_token = await get_csrf_token()
        if not csrf_token:
            print("❌ Failed to get CSRF token for SMS fetch")
            if await login():
                csrf_token = await get_csrf_token()
            if not csrf_token:
                print("❌ Still no CSRF token after login")
                return []
        
        headers = SMS_HEADERS.copy()
        headers["X-CSRF-TOKEN"] = csrf_token
        
        today = datetime.now().strftime('%d-%m-%Y')
        payload = f"_token={csrf_token}&from={today}&to="
        
        print(f"📡 Requesting SMS list for date: {today}")
        response = session.post(SMS_LIST_URL, headers=headers, data=payload, timeout=TIMEOUT)
        response.raise_for_status()
        
        response_text = decode_response(response)
        soup = BeautifulSoup(response_text, 'html.parser')
        
        items = soup.find_all('div', class_='item')
        print(f"📊 Found {len(items)} SMS ranges")
        
        if len(items) == 0:
            print("⚠️ No SMS ranges found in response")
            print("Raw response preview:", response_text[:500])
        
        sms_list = []
        sms_cache = load_sms_cache()
        
        for i, item in enumerate(items):
            try:
                range_div = item.find('div', class_='col-sm-4')
                if not range_div:
                    print(f"❌ No range div found in item {i}")
                    continue
                    
                range_name = range_div.text.strip()
                if not range_name:
                    print(f"❌ Empty range name in item {i}")
                    continue
                
                count_p = item.find('p', string=re.compile(r'^\d+$'))
                count = count_p.text if count_p else "0"
                
                print(f"🔍 Processing range: {range_name} (Count: {count})")
                
                numbers = await fetch_numbers(range_name, csrf_token)
                if not numbers:
                    print(f"⚠️ No numbers found for range: {range_name}")
                    continue
                
                print(f"📱 Found {len(numbers)} numbers in {range_name}: {numbers}")
                
                for num in numbers:
                    try:
                        print(f"🔍 Fetching SMS details for number: {num}")
                        sms_details_list = await fetch_sms_details(num, range_name, csrf_token)
                        
                        if not sms_details_list:
                            print(f"⚠️ No SMS details found for {num}")
                            continue
                        
                        for sms_details in sms_details_list:
                            message = sms_details.get('message', 'No message available')
                            service = sms_details.get('service', 'Unknown')
                            
                            message_id = f"{num}_{hash(message)}"
                            
                            if message_id in sms_cache:
                                print(f"⏭️ Skipping cached message: {message_id}")
                                continue
                            
                            country_name = extract_country(range_name)
                            country_emoji = get_country_emoji(country_name)
                            otp = extract_otp(message)
                            
                            print(f"📨 New SMS found - Number: {num}, Service: {service}, OTP: {otp}")
                            
                            sms_entry = {
                                "range": range_name,
                                "count": count,
                                "country": country_name,
                                "country_emoji": country_emoji,
                                "service": service,
                                "number": num,
                                "otp": otp,
                                "full_message": message,
                                "message_id": message_id
                            }
                            
                            sms_list.append(sms_entry)
                            sms_cache[message_id] = {"timestamp": datetime.now().isoformat()}
                            save_sms_cache(sms_cache)
                            
                    except Exception as e:
                        print(f"❌ Error processing number {num}: {e}")
                        continue
                        
            except Exception as e:
                print(f"❌ Error processing SMS range item {i}: {e}")
                continue
        
        print(f"✅ Total new SMS messages found: {len(sms_list)}")
        return sms_list
        
    except Exception as e:
        print(f"❌ Critical error in fetch_sms: {e}")
        return []

async def fetch_numbers(range_name, csrf_token):
    try:
        print(f"📱 Fetching numbers for range: {range_name}")
        
        headers = SMS_HEADERS.copy()
        headers["X-CSRF-TOKEN"] = csrf_token
        
        today = datetime.now().strftime('%d-%m-%Y')
        payload = f"_token={csrf_token}&start={today}&end=&range={range_name}"
        
        response = session.post(SMS_NUMBERS_URL, headers=headers, data=payload, timeout=TIMEOUT)
        response.raise_for_status()
        
        response_text = decode_response(response)
        soup = BeautifulSoup(response_text, 'html.parser')
        
        number_divs = soup.find_all('div', class_='col-sm-4')
        numbers = []
        
        for div in number_divs:
            number_text = div.text.strip()
            if number_text and re.match(r'^\d+$', number_text):
                numbers.append(number_text)
        
        print(f"📊 Found {len(numbers)} numbers for {range_name}")
        return numbers
        
    except Exception as e:
        print(f"❌ Error fetching numbers for {range_name}: {e}")
        return []

async def fetch_sms_details(number, range_name, csrf_token):
    try:
        print(f"📨 Fetching SMS details for {number} in {range_name}")
        
        headers = SMS_HEADERS.copy()
        headers["X-CSRF-TOKEN"] = csrf_token
        
        today = datetime.now().strftime('%d-%m-%Y')
        payload = f"_token={csrf_token}&start={today}&end=&Number={number}&Range={range_name}"
        
        response = session.post(SMS_DETAILS_URL, headers=headers, data=payload, timeout=TIMEOUT)
        response.raise_for_status()
        
        response_text = decode_response(response)
        soup = BeautifulSoup(response_text, 'html.parser')
        
        sms_cards = soup.find_all('div', class_='card-body')
        sms_details_list = []
        
        for card in sms_cards:
            service_div = card.find('div', class_='col-sm-4')
            message_div = card.find('div', class_='col-9')
            
            if service_div and message_div:
                service_raw = service_div.text.strip().replace('CLI', '').strip()
                message = message_div.find('p').text.strip() if message_div.find('p') else "No message found"
                
                service_from_message = extract_service(message)
                service = service_from_message if service_from_message != "Unknown" else service_raw
                
                print(f"📄 SMS Details - Service: {service}, Message: {message[:50]}...")
                
                sms_details_list.append({
                    "message": message,
                    "service": service
                })
        
        if not sms_details_list:
            print(f"⚠️ No SMS details found for {number}")
            sms_details_list = [{"message": "No message found", "service": "Unknown"}]
        
        return sms_details_list
        
    except Exception as e:
        print(f"❌ Error fetching SMS details for {number}: {e}")
        return [{"message": "Error fetching message", "service": "Unknown"}]

def extract_country(range_name):
    if not range_name:
        return "Unknown"
    
    parts = range_name.split()
    if len(parts) >= 2:
        country_part = parts[0].upper()
        if country_part == "IVORY":
            return "Côte d'Ivoire"
        elif country_part == "USA":
            return "United States"
        elif country_part == "UK":
            return "United Kingdom"
        else:
            return country_part.capitalize()
    return "Unknown"

def extract_service(message):
    for service, pattern in SERVICE_PATTERNS.items():
        if re.search(pattern, message, re.IGNORECASE):
            return service
    return "Unknown"

def extract_otp(text):
    if not text or text == "No message found":
        return "No OTP found"
    
    otp_patterns = [
        r'\b(\d{4,8})\b',
        r'código[:\s]+(\d{4,8})',
        r'code[:\s]+(\d{4,8})',
        r'verification[:\s]+(\d{4,8})',
        r'confirmación[:\s]+(\d{4,8})',
        r'(\d{3}\s\d{3})',
        r'PIN[:\s]+(\d{4,8})',
        r'OTP[:\s]+(\d{4,8})'
    ]
    
    for pattern in otp_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return "No OTP found"

async def send_sms_to_telegram(bot, sms):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        country_emoji = sms['country_emoji']
        country = html.escape(sms['country'])
        service = html.escape(sms['service'])
        formatted_otp = html.escape(format_otp_with_spaces(sms['otp']))
        number = html.escape(sms['number'])
        full_message = html.escape(sms['full_message'])
        
        message = (
            f"{country_emoji} <b>{country} {service} SMS Received...</b>\n\n"
            f"🔢 <b>OTP :</b> <code>{formatted_otp}</code>\n\n"
            f"⏰ <b>Time :</b> <code>{timestamp}</code>\n"
            f"🎯 <b>Service :</b> <code>{service}</code>\n"
            f"💰 <b>Payment :</b> <code>Paid</code>\n"
            f"📱 <b>Phone :</b> <code>{number}</code>\n\n"
            f"<pre>{full_message}</pre>"
        )
        
        print(f"📤 Sending SMS to Telegram for {number}")
        
        for chat_id in CHAT_IDS:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML"
                )
                print(f"✅ Successfully sent SMS to chat {chat_id}")
            except telegram.error.RetryAfter as e:
                print(f"⏳ Rate limit hit for chat {chat_id}, retrying after {e.retry_after} seconds")
                await asyncio.sleep(e.retry_after + 1)
                await bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML"
                )
                print(f"✅ Successfully sent SMS to chat {chat_id} after retry")
            except telegram.error.BadRequest as e:
                if "chat not found" in str(e).lower():
                    print(f"❌ Chat not found: {chat_id}")
                else:
                    print(f"❌ Telegram BadRequest error for chat {chat_id}: {e}")
            except Exception as e:
                print(f"❌ Error sending to chat {chat_id}: {e}")
                
    except Exception as e:
        print(f"❌ Error formatting message for {sms['message_id']}: {e}")

async def send_start_alert(bot):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            "🤖 <b>Bot Started Successfully</b>\n\n"
            f"⏰ <b>Time:</b> <code>{timestamp}</code>\n"
            "📡 <b>Status:</b> <code>Monitoring for SMS messages</code>"
        )
        
        for chat_id in CHAT_IDS:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML"
                )
                print(f"✅ Successfully sent start alert to chat {chat_id}")
            except telegram.error.RetryAfter as e:
                print(f"⏳ Rate limit hit for start alert to {chat_id}, retrying after {e.retry_after} seconds")
                await asyncio.sleep(e.retry_after + 1)
                await bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML"
                )
                print(f"✅ Successfully sent start alert to chat {chat_id} after retry")
            except telegram.error.BadRequest as e:
                if "chat not found" in str(e).lower():
                    print(f"❌ Chat not found: {chat_id}")
                else:
                    print(f"❌ Telegram BadRequest error for start alert to {chat_id}: {e}")
            except Exception as e:
                print(f"❌ Error sending start alert to {chat_id}: {e}")
    except Exception as e:
        print(f"❌ Error sending start alert: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message and update.message.chat_id:
            await update.message.reply_text("🤖 Bot is running! Monitoring for SMS updates.", parse_mode="HTML")
        elif update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🤖 Bot is running! Monitoring for SMS updates.",
                parse_mode="HTML"
            )
        else:
            print("⚠️ No valid chat found for /start command")
    except Exception as e:
        print(f"❌ Error in start handler: {e}")

async def main():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    def signal_handler():
        print("\n🛑 Shutting down gracefully...")
        stop_event.set()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        print("🚀 Initializing SMS Bot...")
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        await send_start_alert(application.bot)
        
        last_login_time = time.time()
        if await login():
            print("✅ Initial login successful, starting monitoring...")
            
            while not stop_event.is_set():
                try:
                    success, last_login_time = await refresh_session(last_login_time)
                    if not success:
                        print("❌ Session refresh failed, retrying...")
                        await asyncio.sleep(10)
                        continue
                    
                    sms_list = await fetch_sms()
                    
                    if sms_list:
                        print(f"📨 Processing {len(sms_list)} new SMS messages")
                        
                        for i in range(0, len(sms_list), MAX_BATCH_SIZE):
                            batch = sms_list[i:i+MAX_BATCH_SIZE]
                            
                            for sms in batch:
                                print(f"🔄 Processing SMS: {sms['number']} - {sms['service']} - OTP: {sms['otp']}")
                                
                                if check_and_save_otp(sms['number'], sms['otp'], sms['message_id']):
                                    print(f"📤 Sending new SMS for {sms['number']}")
                                    await send_sms_to_telegram(application.bot, sms)
                                else:
                                    print(f"⏭️ Skipped duplicate OTP for {sms['number']}: {sms['otp']}")
                            
                            if i + MAX_BATCH_SIZE < len(sms_list):
                                print(f"⏳ Processed batch, waiting {BATCH_DELAY} seconds...")
                                await asyncio.sleep(BATCH_DELAY)
                    else:
                        print("📭 No new SMS messages found")
                    
                    print("⏳ Waiting 5 seconds before next check...")
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    print(f"❌ Error in main monitoring loop: {e}")
                    await asyncio.sleep(10)
        else:
            print("❌ Initial login failed - cannot start monitoring")
            
    except Exception as e:
        print(f"💀 Fatal error during startup: {e}")
    finally:
        print("🛑 Shutting down bot...")
        try:
            await application.stop()
            await application.shutdown()
        except Exception:
            pass
        print("✅ Bot stopped successfully")

if __name__ == "__main__":
    print("🚀 Starting IVAS SMS Scraper Bot...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user")
    except Exception as e:

        print(f"💀 Fatal error: {e}")
