from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue, Empty, Full
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import escape
from contextlib import contextmanager
import os
import base64
import hashlib
import hmac
import socket
import json
import sqlite3
import threading
import time


ROOT = Path(__file__).resolve().parent
DB_FILE = Path(os.environ.get("DB_PATH", str(ROOT / "data" / "tiempo_aph.db")))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = 9010
MET_NORWAY_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
MET_USER_AGENT = os.environ.get("MET_USER_AGENT", "")
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "")
OPERATOR_USER = os.environ.get("OPERATOR_USER", "")
PASSWORD_HASH = os.environ.get("OPERATOR_PASSWORD_HASH", "")
FONT_DIR = Path(os.environ.get("FONT_DIR", str(ROOT / "assets" / "fonts")))
CLIENTS_LOCK = threading.RLock()
REFRESH_LOCK = threading.Lock()
LAST_REFRESH = 0.0

CLIENTS = set()
DB_LOCK = threading.RLock()
DB_READY = False

WEATHER_CITIES = [
    {"slug": "la-paz", "name": "LA PAZ", "latitude": -16.4897, "longitude": -68.1193},
    {"slug": "santa-cruz", "name": "SANTA CRUZ", "latitude": -17.7833, "longitude": -63.1821},
    {"slug": "cochabamba", "name": "COCHABAMBA", "latitude": -17.3895, "longitude": -66.1568},
    {"slug": "sucre", "name": "SUCRE", "latitude": -19.0196, "longitude": -65.2619},
    {"slug": "oruro", "name": "ORURO", "latitude": -17.9833, "longitude": -67.1500},
    {"slug": "potosi", "name": "POTOSI", "latitude": -19.5836, "longitude": -65.7531},
    {"slug": "tarija", "name": "TARIJA", "latitude": -21.5355, "longitude": -64.7296},
    {"slug": "trinidad", "name": "TRINIDAD", "latitude": -14.8333, "longitude": -64.9000},
    {"slug": "cobija", "name": "COBIJA", "latitude": -11.0267, "longitude": -68.7692},
]
WEATHER_CITY_MAP = {city["slug"]: city for city in WEATHER_CITIES}

DEFAULT_STATE = {
    "outputMode": "",
    "weatherCity": "santa-cruz",
    "updatedAt": "",
}


def now_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def connect_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    global DB_READY
    with DB_LOCK, connect_db() as conn:
        if DB_READY:
            return
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS forecast_days (city_slug TEXT, date TEXT, payload TEXT NOT NULL, PRIMARY KEY(city_slug,date))")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_cache (
                city_slug TEXT PRIMARY KEY,
                city_name TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                fetched_at TEXT NOT NULL,
                current_time TEXT NOT NULL,
                current_temperature REAL NOT NULL,
                current_code INTEGER NOT NULL,
                current_wind_speed REAL NOT NULL,
                current_wind_direction REAL NOT NULL,
                current_is_day INTEGER NOT NULL,
                today_date TEXT NOT NULL,
                today_min REAL NOT NULL,
                today_max REAL NOT NULL,
                today_code INTEGER NOT NULL,
                today_wind_speed REAL NOT NULL,
                today_wind_direction REAL NOT NULL,
                tomorrow_date TEXT NOT NULL,
                tomorrow_min REAL NOT NULL,
                tomorrow_max REAL NOT NULL,
                tomorrow_code INTEGER NOT NULL,
                tomorrow_wind_speed REAL NOT NULL,
                tomorrow_wind_direction REAL NOT NULL,
                raw_json TEXT NOT NULL
            )
            """
        )
        DB_READY = True


def read_kv(conn, key, fallback):
    row = conn.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
    if not row:
        return fallback
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return fallback


def normalize_state(incoming):
    incoming = incoming or {}
    city = str(incoming.get("weatherCity", DEFAULT_STATE["weatherCity"]))
    mode = str(incoming.get("outputMode", incoming.get("mode", "")))
    if city not in WEATHER_CITY_MAP:
        city = DEFAULT_STATE["weatherCity"]
    if mode not in {"", "weather"}:
        mode = ""
    return {
        "outputMode": mode,
        "weatherView": "extended" if incoming.get("weatherView") == "extended" else "current",
        "weatherCity": city,
        "updatedAt": str(incoming.get("updatedAt", "")),
    }


def read_state():
    with DB_LOCK:
        init_db()
        with connect_db() as conn:
            raw = {
                "outputMode": read_kv(conn, "outputMode", ""),
                "weatherView": read_kv(conn, "weatherView", "current"),
                "weatherCity": read_kv(conn, "weatherCity", "santa-cruz"),
                "updatedAt": read_kv(conn, "updatedAt", ""),
            }
    return normalize_state(raw)


def save_state(incoming):
    state = normalize_state(incoming)
    state["updatedAt"] = now_utc_iso()
    with DB_LOCK:
        init_db()
        with connect_db() as conn:
            for key in ("outputMode", "weatherCity", "weatherView", "updatedAt"):
                conn.execute(
                    "INSERT OR REPLACE INTO kv_store(key, value) VALUES(?, ?)",
                    (key, json.dumps(state[key], ensure_ascii=False)),
                )
        broadcast_state(state)
    return state


def set_output_state(payload):
    with DB_LOCK:
        return _set_output_state(payload)

def _set_output_state(payload):
    state = read_state()
    mode = str(payload.get("mode", "")).strip()
    city_slug = str(payload.get("weatherCity", state["weatherCity"])).strip()
    if mode not in {"", "weather"}:
        return {"ok": False, "message": "Modo de salida invalido.", "state": state}
    if mode == "weather":
        if city_slug not in WEATHER_CITY_MAP:
            return {"ok": False, "message": "Ciudad invalida.", "state": state}
        if not read_weather_city(city_slug):
            return {"ok": False, "message": "Primero consulta y guarda los datos del tiempo.", "state": state}
        state["weatherCity"] = city_slug
        state["weatherView"] = "extended" if payload.get("weatherView") == "extended" else "current"
    state["outputMode"] = mode
    return {"ok": True, "message": "Salida actualizada.", "state": save_state(state)}


def broadcast_state(state):
    with CLIENTS_LOCK:
        for client in list(CLIENTS):
            try:
                client.put_nowait(state)
            except Full:
                try:
                    client.get_nowait()
                    client.put_nowait(state)
                except (Empty, Full):
                    pass


def met_norway_url(city):
    return f"{MET_NORWAY_URL}?{urlencode({'lat': city['latitude'], 'lon': city['longitude']})}"


def fetch_met_norway_city(city, attempts=2):
    if not MET_USER_AGENT:
        raise RuntimeError("Configura MET_USER_AGENT con contacto real.")
    last_error = None
    for attempt in range(attempts):
        try:
            request = Request(
                met_norway_url(city),
                headers={"User-Agent": MET_USER_AGENT, "Accept": "application/json"},
            )
            with urlopen(request, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, HTTPError) and error.code in (400, 403, 429):
                raise RuntimeError(f"MET Norway HTTP {error.code}; no se reintenta") from error
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"{city['name']}: {last_error}")


def fetch_met_norway(attempts=2):
    results = {}
    errors = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_met_norway_city, city, attempts): city for city in WEATHER_CITIES}
        for future in as_completed(futures):
            city = futures[future]
            try:
                results[city["slug"]] = future.result()
            except Exception as error:
                errors.append(str(error))
    if errors:
        raise RuntimeError("No se pudo completar MET Norway: " + " | ".join(errors))
    return [results[city["slug"]] for city in WEATHER_CITIES]


def met_symbol_code(entry):
    data = entry.get("data") or {}
    for period in ("next_1_hours", "next_6_hours", "next_12_hours"):
        code = ((data.get(period) or {}).get("summary") or {}).get("symbol_code")
        if code:
            return str(code)
    return "cloudy"


def symbol_to_weather_code(symbol):
    value = str(symbol or "").lower()
    if "thunder" in value:
        return 95
    if "snow" in value:
        return 73
    if "sleet" in value:
        return 66
    if "heavyrain" in value:
        return 65
    if "rain" in value:
        return 61
    if "fog" in value:
        return 45
    if "partlycloudy" in value:
        return 2
    if "cloudy" in value:
        return 3
    if "fair" in value:
        return 1
    if "clearsky" in value:
        return 0
    return 3


def parse_weather_payloads(payloads):
    if len(payloads) != len(WEATHER_CITIES):
        raise ValueError("Se requieren las nueve ciudades")
    fetched_at = now_utc_iso()
    local_zone = timezone(timedelta(hours=-4))
    local_now = datetime.now(local_zone)
    today_key = local_now.date().isoformat()
    tomorrow_key = (local_now.date() + timedelta(days=1)).isoformat()
    parsed = []

    for city, payload in zip(WEATHER_CITIES, payloads):
        series = ((payload.get("properties") or {}).get("timeseries") or [])
        if not series:
            raise ValueError(f"MET Norway no devolvio datos para {city['name']}")

        hourly = []
        for entry in series:
            try:
                moment = datetime.fromisoformat(str(entry["time"]).replace("Z", "+00:00")).astimezone(local_zone)
                details = entry["data"]["instant"]["details"]
                hourly.append({
                    "time": moment,
                    "temperature": float(details["air_temperature"]),
                    "wind_speed": float(details.get("wind_speed", 0)) * 3.6,
                    "wind_direction": float(details.get("wind_from_direction", 0)),
                    "symbol": met_symbol_code(entry),
                })
            except (KeyError, TypeError, ValueError):
                continue

        if not hourly:
            raise ValueError(f"Datos horarios invalidos para {city['name']}")
        current = min(hourly, key=lambda item: abs((item["time"] - local_now).total_seconds()))

        def daily_values(date_key):
            items = [item for item in hourly if item["time"].date().isoformat() == date_key]
            if not items:
                raise ValueError(f"Pronostico incompleto para {city['name']} ({date_key})")
            strongest_wind = max(items, key=lambda item: item["wind_speed"])
            return {
                "date": date_key,
                "min": min(item["temperature"] for item in items),
                "max": max(item["temperature"] for item in items),
                "code": max(symbol_to_weather_code(item["symbol"]) for item in items),
                "wind_speed": strongest_wind["wind_speed"],
                "wind_direction": strongest_wind["wind_direction"],
            }

        today = daily_values(today_key)
        tomorrow = daily_values(tomorrow_key)
        extended = [daily_values((local_now.date() + timedelta(days=offset)).isoformat()) for offset in range(1, 5)]
        parsed.append({
            **city,
            "fetched_at": fetched_at,
            "current_time": current["time"].isoformat(),
            "current_temperature": current["temperature"],
            "current_code": symbol_to_weather_code(current["symbol"]),
            "current_wind_speed": current["wind_speed"],
            "current_wind_direction": current["wind_direction"],
            "current_is_day": int(6 <= current["time"].hour < 19),
            "today_date": today["date"],
            "today_min": today["min"],
            "today_max": today["max"],
            "today_code": today["code"],
            "today_wind_speed": today["wind_speed"],
            "today_wind_direction": today["wind_direction"],
            "tomorrow_date": tomorrow["date"],
            "tomorrow_min": tomorrow["min"],
            "tomorrow_max": tomorrow["max"],
            "tomorrow_code": tomorrow["code"],
            "tomorrow_wind_speed": tomorrow["wind_speed"],
            "tomorrow_wind_direction": tomorrow["wind_direction"],
            "raw_json": json.dumps(payload, ensure_ascii=False),
            "extended": extended,
        })
    return parsed


def _refresh_weather_cache():
    try:
        rows = parse_weather_payloads(fetch_met_norway())
    except Exception as error:
        return {"ok": False, "message": str(error), **weather_cache_status()}

    with DB_LOCK:
        init_db()
        with connect_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for row in rows:
                conn.execute("DELETE FROM forecast_days WHERE city_slug=?", (row["slug"],))
                for day in row["extended"]:
                    conn.execute("INSERT INTO forecast_days VALUES(?,?,?)", (row["slug"], day["date"], json.dumps(day)))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO weather_cache VALUES (
                        :slug,:name,:latitude,:longitude,:fetched_at,:current_time,
                        :current_temperature,:current_code,:current_wind_speed,:current_wind_direction,:current_is_day,
                        :today_date,:today_min,:today_max,:today_code,:today_wind_speed,:today_wind_direction,
                        :tomorrow_date,:tomorrow_min,:tomorrow_max,:tomorrow_code,:tomorrow_wind_speed,:tomorrow_wind_direction,
                        :raw_json
                    )
                    """,
                    row,
                )
    with DB_LOCK:
        save_state(read_state())
    return {"ok": True, "message": "Se consulto una vez MET Norway y se guardaron los 9 departamentos en la base local.", **weather_cache_status()}


def refresh_weather_cache():
    global LAST_REFRESH
    if not REFRESH_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "Consulta en curso."}
    try:
        if time.monotonic() - LAST_REFRESH < 600:
            return {"ok": False, "message": "Espera diez minutos entre consultas.", **weather_cache_status()}
        LAST_REFRESH = time.monotonic()
        return _refresh_weather_cache()
    finally:
        REFRESH_LOCK.release()


def weather_row_to_dict(row):
    if not row:
        return None
    return {key: row[key] for key in row.keys() if key != "raw_json"}


def read_weather_city(city_slug):
    if city_slug not in WEATHER_CITY_MAP:
        return None
    with DB_LOCK:
        init_db()
        with connect_db() as conn:
            return weather_row_to_dict(conn.execute("SELECT * FROM weather_cache WHERE city_slug=?", (city_slug,)).fetchone())


def weather_cache_status():
    with DB_LOCK:
        init_db()
        with connect_db() as conn:
            rows = conn.execute("SELECT * FROM weather_cache").fetchall()
    by_slug = {row["city_slug"]: weather_row_to_dict(row) for row in rows}
    cities = []
    for city in WEATHER_CITIES:
        item = by_slug.get(city["slug"])
        cities.append({
            "slug": city["slug"],
            "name": city["name"],
            "ready": bool(item),
            "extendedReady": bool(item) and len(read_forecast(city["slug"])) == 4,
            "fetchedAt": item["fetched_at"] if item else "",
            "currentTemperature": item["current_temperature"] if item else None,
            "todayMin": item["today_min"] if item else None,
            "todayMax": item["today_max"] if item else None,
            "todayWindSpeed": item["today_wind_speed"] if item else None,
            "tomorrowMin": item["tomorrow_min"] if item else None,
            "tomorrowMax": item["tomorrow_max"] if item else None,
            "tomorrowWindSpeed": item["tomorrow_wind_speed"] if item else None,
        })
    updated_at = max((item["fetched_at"] for item in by_slug.values()), default="")
    return {"ready": len(by_slug) == len(WEATHER_CITIES), "updatedAt": updated_at, "cities": cities}


def weather_icon(code, is_day=True):
    code = int(code)
    if code == 0:
        return "☀" if is_day else "☾"
    if code in (1, 2):
        return "🌤"
    if code == 3:
        return "☁"
    if code in (45, 48):
        return "≋"
    if code in (51, 53, 55, 56, 57):
        return "🌦"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "🌧"
    if code in (71, 73, 75, 77, 85, 86):
        return "❄"
    if code in (95, 96, 99):
        return "⛈"
    return "☁"


def wind_direction_label(degrees):
    labels = ["NORTE", "NORESTE", "ESTE", "SURESTE", "SUR", "SUROESTE", "OESTE", "NOROESTE"]
    return labels[int((float(degrees) + 22.5) // 45) % 8]


def read_forecast(city_slug):
    init_db()
    with connect_db() as conn:
        return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM forecast_days WHERE city_slug=? ORDER BY date", (city_slug,))]


def weather_overlay_html(city_slug, view="current"):
    from graphics import render_weather
    with DB_LOCK:
        return render_weather(read_weather_city(city_slug), read_forecast(city_slug), view)


def legacy_weather_overlay_html(city_slug):
    data = read_weather_city(city_slug)
    if not data:
        return """<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}</style></head><body></body></html>"""

    icon_current = weather_icon(data["current_code"], bool(data["current_is_day"]))
    icon_min = weather_icon(data["today_code"], True)
    icon_max = weather_icon(data["today_code"], True)
    current = round(data["current_temperature"])
    min_temp = round(data["today_min"])
    max_temp = round(data["today_max"])
    wind_speed = round(data["today_wind_speed"])
    wind_direction = wind_direction_label(data["today_wind_direction"])
    city_name = escape(data["city_name"])

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{city_name} - APH Datos del tiempo</title>
  <link rel="stylesheet" href="/styles.css?v=20260710-aph3">
</head>
<body class="vmix-body">
  <main class="aph-stage">
    <section class="aph-title">
      <h1>DATOS</h1>
      <p>DEL <strong>TIEMPO</strong></p>
    </section>
    <section class="city-tag">
      <span class="pin" aria-hidden="true"></span>
      <strong>{city_name}</strong>
    </section>
    <section class="weather-deck">
      <article class="weather-card card-current">
        <header>ACTUAL</header>
        <div class="temp">{current}°</div>
        <div class="weather-symbol">{icon_current}</div>
      </article>
      <article class="weather-card card-small">
        <header>MIN.</header>
        <div class="temp">{min_temp}°</div>
        <div class="weather-symbol">{icon_min}</div>
      </article>
      <article class="weather-card card-small">
        <header>MAX.</header>
        <div class="temp">{max_temp}°</div>
        <div class="weather-symbol">{icon_max}</div>
      </article>
    </section>
    <section class="wind-ribbon">VIENTOS DEL {wind_direction} {wind_speed} KM/H.</section>
  </main>
</body>
</html>"""


class ReliableThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(64)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            request.settimeout(20)
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class APHHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "APH"
    sys_version = ""
    STATIC = {"/output.html", "/app.js", "/styles.css", "/graphics.css", "/fonts.css"}
    FONTS = {"GalanoGrotesqueRegular.otf", "GalanoGrotesqueBold.otf"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def handle(self):
        try:
            super().handle()
        except (ConnectionError, TimeoutError, socket.timeout):
            pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; connect-src 'self'")
        super().end_headers()

    def authenticated(self):
        try:
            scheme, value = self.headers.get("Authorization", "").split(" ", 1)
            if scheme.lower() != "basic":
                raise ValueError()
            user, password = base64.b64decode(value, validate=True).decode().split(":", 1)
            iterations, salt, expected = PASSWORD_HASH.split(":")
            digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
            valid = hmac.compare_digest(user, OPERATOR_USER) and hmac.compare_digest(digest, expected)
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            time.sleep(0.3)
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="APH operador", charset="UTF-8"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        return valid

    def do_OPTIONS(self):
        self.send_error(405)

    def do_HEAD(self):
        self.do_GET(head_only=True)

    def translate_path(self, path):
        path = urlparse(path).path
        if path.startswith("/assets/fonts/"):
            return str(FONT_DIR / path.rsplit("/", 1)[-1])
        return str(ROOT / ("index.html" if path == "/" else path.lstrip("/")))

    def do_GET(self, head_only=False):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        self.head_only = head_only
        if path in ("/", "/index.html"):
            if self.authenticated():
                super().do_HEAD() if head_only else super().do_GET()
        elif path == "/healthz":
            try:
                with connect_db() as conn:
                    conn.execute("SELECT 1 FROM kv_store LIMIT 1").fetchall()
                self.write_json({"ok": True})
            except sqlite3.Error:
                self.send_error(503)
        elif path == "/api/state":
            self.write_json(read_state())
        elif path == "/api/weather":
            self.write_json({"ok": True, **weather_cache_status()})
        elif path == "/api/events" and not head_only:
            self.write_events()
        elif path == "/weather/local":
            self.write_html(weather_overlay_html(query.get("city", ["santa-cruz"])[0], query.get("view", ["current"])[0]))
        elif path in self.STATIC or (path.startswith("/assets/fonts/") and path.rsplit("/", 1)[-1] in self.FONTS and path.count("/") == 3):
            super().do_HEAD() if head_only else super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        self.close_connection = True
        if not self.authenticated():
            return
        if self.headers.get("Origin") != PUBLIC_ORIGIN or self.headers.get("X-APH-Request") != "operator":
            self.send_error(403, "Origen o proteccion CSRF invalida")
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError()
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 8192:
                self.send_error(413)
                return
            if length and self.headers.get_content_type() != "application/json":
                self.send_error(415)
                return
            payload = json.loads(self.rfile.read(length).decode()) if length else {}
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            self.send_error(400, "JSON invalido")
            return
        path = urlparse(self.path).path
        if path == "/api/weather/refresh":
            self.write_json(refresh_weather_cache())
        elif path == "/api/output":
            self.write_json(set_output_state(payload))
        elif path == "/api/state":
            self.write_json(set_output_state({"mode": payload.get("outputMode", ""), **payload}))
        else:
            self.send_error(404)

    def write_json(self, payload):
        self.write_bytes(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def write_html(self, html):
        self.write_bytes(html.encode(), "text/html; charset=utf-8")

    def write_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not getattr(self, "head_only", False):
            self.wfile.write(data)

    def write_events(self):
        queue = Queue(maxsize=8)
        with DB_LOCK, CLIENTS_LOCK:
            if len(CLIENTS) >= 24:
                self.send_error(503)
                return
            initial_state = read_state()
            CLIENTS.add(queue)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.write_event(initial_state)
            while True:
                try:
                    self.write_event(queue.get(timeout=10))
                except Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (ConnectionError, TimeoutError):
            pass
        finally:
            with CLIENTS_LOCK:
                CLIENTS.discard(queue)

    def write_event(self, state):
        self.wfile.write(f"data: {json.dumps(state, ensure_ascii=False)}\n\n".encode())
        self.wfile.flush()


def validate_config():
    if not OPERATOR_USER or not PASSWORD_HASH or not PUBLIC_ORIGIN.startswith("https://"):
        raise RuntimeError("Configura OPERATOR_USER, OPERATOR_PASSWORD_HASH y PUBLIC_ORIGIN HTTPS.")
    iterations, salt, digest = PASSWORD_HASH.split(":")
    if int(iterations) < 600000 or len(bytes.fromhex(salt)) < 16 or len(bytes.fromhex(digest)) != 32:
        raise RuntimeError("Hash de operador invalido")


if __name__ == "__main__":
    validate_config()
    init_db()
    server = ReliableThreadingHTTPServer((HOST, PORT), APHHandler)
    print(f"APH escuchando en {HOST}:{PORT}", flush=True)
    server.serve_forever(poll_interval=0.2)
