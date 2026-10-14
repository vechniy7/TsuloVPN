"""Лимит устройств и цены за доп. слоты."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone

from config import config

# Базовый тариф включает 1 устройство. Доп. слоты 2..5:
# слот 2 = 35 ₽, каждый следующий +5 ₽.
BASE_DEVICE_SLOTS = 1
MAX_DEVICE_SLOTS = 5
FIRST_EXTRA_SLOT_PRICE = 35
EXTRA_SLOT_STEP = 5
BASE_MONTHLY_PRICE = 69

# Android factory/codename → человекочитаемое имя (Happ на Android часто шлёт Build.DEVICE).
_DEVICE_MODEL_ALIASES: dict[str, str] = {
    # Xiaomi 14T / 14T Pro (то, что было у клиента как «буквы и цифры»)
    "2407FPN8EG": "Xiaomi 14T Pro",
    "2407FPN8GA": "Xiaomi 14T Pro",
    "2407FPN8QG": "Xiaomi 14T Pro",
    "rothko": "Xiaomi 14T Pro",
    "ROTHKO": "Xiaomi 14T Pro",
    "2406APNFAG": "Xiaomi 14T",
    "2409FPCC4G": "Xiaomi 14T",
    "beryl": "Xiaomi 14T",
    "BERYL": "Xiaomi 14T",
    "2311DRK48G": "Xiaomi 14",
    "23113RKC6G": "Xiaomi 14 Pro",
    "23127PN0CG": "Xiaomi 14 Ultra",
    "2211133C": "Xiaomi 13",
    "2210132C": "Xiaomi 13 Pro",
    "2210132G": "Xiaomi 13 Pro",
    "2304FPN6DC": "Xiaomi 13 Ultra",
    "2201123G": "Xiaomi 12",
    "2201122G": "Xiaomi 12 Pro",
    "2203121C": "Xiaomi 12S Ultra",
    "23078PND5G": "Poco F5",
    "23013PC75G": "Poco F5",
    "23049PCD8G": "Redmi Note 12",
    "23021RAA2Y": "Redmi Note 12 5G",
    "22101316G": "Redmi Note 12 Pro",
    "2201116SG": "Redmi Note 11",
    "21061119DG": "Redmi 10",
    "M2101K6G": "Redmi Note 10 Pro",
    "M2102J20SG": "Poco X3 Pro",
    "24117RK2CG": "Xiaomi 15",
    "2410DPN6CC": "Xiaomi 15 Pro",
    "SM-S918B": "Samsung Galaxy S23 Ultra",
    "SM-S911B": "Samsung Galaxy S23",
    "SM-S928B": "Samsung Galaxy S24 Ultra",
    "SM-S921B": "Samsung Galaxy S24",
    "SM-S938B": "Samsung Galaxy S25 Ultra",
    "SM-A546B": "Samsung Galaxy A54",
    "SM-A556B": "Samsung Galaxy A55",
    "Pixel 8": "Google Pixel 8",
    "Pixel 8 Pro": "Google Pixel 8 Pro",
    "Pixel 9": "Google Pixel 9",
    "Pixel 9 Pro": "Google Pixel 9 Pro",
    "Pixel 9 Pro XL": "Google Pixel 9 Pro XL",
}


def default_device_limit() -> int:
    raw = int(config.DEVICE_LIMIT or BASE_DEVICE_SLOTS)
    return max(BASE_DEVICE_SLOTS, min(MAX_DEVICE_SLOTS, raw))


def clamp_device_limit(value: int | None) -> int:
    try:
        n = int(value if value is not None else default_device_limit())
    except (TypeError, ValueError):
        n = default_device_limit()
    return max(BASE_DEVICE_SLOTS, min(MAX_DEVICE_SLOTS, n))


def user_device_limit(user) -> int:
    if user is None:
        return default_device_limit()
    raw = getattr(user, "device_limit", None)
    if raw is None:
        return default_device_limit()
    return clamp_device_limit(raw)


_HWID_RE = re.compile(r"^[a-zA-Z0-9=\-_.:]{6,128}$")
_MODEL_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{4,31}$")


def _try_parse_nested(value):
    """Распарсить JSON / Python-repr вложенных HWID-записей."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return s
    if not (s.startswith("{") or s.startswith("[")):
        return s
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        return ast.literal_eval(s)
    except Exception:
        return s


def extract_raw_hwid(value) -> str:
    """Достать настоящий HWID из строки / dict / вложенного str(dict)."""
    meta = unwrap_device_meta(value)
    return str(meta.get("hwid") or "")


def unwrap_device_meta(value) -> dict:
    """
    Разворачивает вложенный str(dict)/JSON и собирает hwid + name/os/last_seen
    с самого глубокого осмысленного уровня.
    """
    hwid = ""
    name = ""
    os_name = ""
    last_seen = ""
    current = value
    for _ in range(12):
        current = _try_parse_nested(current)
        if isinstance(current, dict):
            maybe_name = str(current.get("name") or current.get("model") or "").strip()
            maybe_os = str(current.get("os") or "").strip()
            maybe_seen = str(current.get("last_seen") or "").strip()
            if maybe_name and not maybe_name.startswith("{") and "hwid" not in maybe_name[:12]:
                name = maybe_name
            if maybe_os and not maybe_os.startswith("{"):
                os_name = maybe_os
            if maybe_seen and not maybe_seen.startswith("{"):
                last_seen = maybe_seen
            nxt = current.get("hwid") or current.get("id") or current.get("device_id")
            if nxt is None:
                break
            current = nxt
            continue
        s = str(current or "").strip()
        if not s:
            break
        if _HWID_RE.match(s) and not s.startswith("{"):
            hwid = s[:128]
            break
        if s.startswith("{") or s.startswith("'{"):
            current = s
            continue
        cleaned = re.sub(r"[^a-zA-Z0-9=\-_.:]", "", s)
        if cleaned and len(cleaned) >= 6 and "hwid" not in cleaned.lower():
            hwid = cleaned[:128]
        break
    out: dict = {}
    if hwid:
        out["hwid"] = hwid
    if name:
        out["name"] = name
    if os_name:
        out["os"] = os_name
    if last_seen:
        out["last_seen"] = last_seen
    return out


def friendly_device_name(
    model: str | None = None,
    os_name: str | None = None,
    *,
    user_agent: str | None = None,
) -> str:
    """Человекочитаемое имя: iPhone 16 Pro Max / Xiaomi 14T Pro / Android."""
    model = (model or "").strip()
    os_name = (os_name or "").strip()
    ua = (user_agent or "").strip()

    # User-Agent вида: App/1.0 (Android 14; Xiaomi 14T Pro)
    if ua and ("(" in ua and ";" in ua):
        try:
            inside = ua[ua.rfind("(") + 1 : ua.rfind(")")]
            parts = [p.strip() for p in inside.split(";") if p.strip()]
            if len(parts) >= 2:
                maybe = parts[-1]
                if maybe and not _MODEL_CODE_RE.match(maybe):
                    model = model or maybe
                elif maybe and not model:
                    model = maybe
                if not os_name and parts[0]:
                    os_name = parts[0].split()[0]
        except Exception:
            pass

    if model:
        alias = _DEVICE_MODEL_ALIASES.get(model) or _DEVICE_MODEL_ALIASES.get(model.upper())
        if alias:
            return alias
        # Код вида 2407FPN8EG — не показываем как «имя».
        if _MODEL_CODE_RE.match(model) and " " not in model and not re.search(r"[a-z]", model):
            if os_name:
                return f"{os_name}-устройство"
            return "Android-устройство"
        return model[:64]

    if os_name:
        low = os_name.lower()
        if "ios" in low or "iphone" in low:
            return "iPhone"
        if "mac" in low:
            return "Mac"
        if "win" in low:
            return "Windows"
        if "android" in low:
            return "Android-устройство"
        return os_name[:64]
    return ""


def normalize_device_records(raw_items) -> list[dict]:
    """
    Нормализовать bound_hwids:
    - сохранить dict-записи;
    - развернуть вложенные str(dict) / JSON (баг старого парсера);
    - схлопнуть дубликаты по реальному HWID.
    """
    if raw_items is None:
        return []
    if isinstance(raw_items, str):
        try:
            raw_items = json.loads(raw_items)
        except json.JSONDecodeError:
            raw_items = [raw_items] if raw_items.strip() else []
    if not isinstance(raw_items, list):
        return []

    by_hwid: dict[str, dict] = {}
    order: list[str] = []

    def _merge(hwid: str, name: str = "", os_name: str = "", last_seen: str = "") -> None:
        hwid = (hwid or "").strip()[:128]
        if not hwid or hwid.startswith("{"):
            return
        # Отсекаем мусор, где «hwid» — это repr словаря.
        if "hwid" in hwid and ("{" in hwid or "'" in hwid):
            nested = extract_raw_hwid(hwid)
            if not nested or nested == hwid:
                return
            hwid = nested
        if hwid not in by_hwid:
            by_hwid[hwid] = {"hwid": hwid}
            order.append(hwid)
        rec = by_hwid[hwid]
        if name:
            # Не затирать нормальное имя заводским кодом.
            prev = str(rec.get("name") or "")
            if not prev or (
                _MODEL_CODE_RE.match(prev)
                and not _MODEL_CODE_RE.match(name)
            ):
                rec["name"] = name[:64]
            elif not _MODEL_CODE_RE.match(name) and len(name) >= len(prev):
                rec["name"] = name[:64]
        if os_name:
            rec["os"] = os_name[:64]
        if last_seen:
            prev_seen = str(rec.get("last_seen") or "")
            if not prev_seen or last_seen > prev_seen:
                rec["last_seen"] = last_seen

    for item in raw_items:
        meta = unwrap_device_meta(item)
        h = str(meta.get("hwid") or "").strip()
        if not h:
            continue
        name = str(meta.get("name") or "").strip()
        os_name = str(meta.get("os") or "").strip()
        last_seen = str(meta.get("last_seen") or "").strip()
        if name.startswith("{") or "hwid" in name[:20]:
            name = ""
        _merge(
            h,
            name=friendly_device_name(name, os_name) or name,
            os_name=os_name,
            last_seen=last_seen,
        )

    return [by_hwid[h] for h in order if h in by_hwid]


def bound_device_records(user) -> list[dict]:
    """Список устройств: [{hwid, name?, os?, last_seen?}, …] без дублей."""
    if user is None:
        return []
    items = getattr(user, "bound_hwids", None)
    records = normalize_device_records(items)
    if records:
        return records
    legacy = extract_raw_hwid(getattr(user, "bound_hwid", None) or "")
    return [{"hwid": legacy}] if legacy else []


def bound_hwid_list(user) -> list[str]:
    return [r["hwid"] for r in bound_device_records(user) if r.get("hwid")]


def format_device_label(record: dict | str, index: int = 0) -> str:
    """Имя для бота/панели: Xiaomi 14T Pro / iPhone 16 Pro Max — без сырого HWID."""
    if isinstance(record, dict):
        h = extract_raw_hwid(record.get("hwid") or "")
        name = str(record.get("name") or "").strip()
        os_name = str(record.get("os") or "").strip()
    else:
        h = extract_raw_hwid(record)
        name = ""
        os_name = ""

    pretty = friendly_device_name(name, os_name) or name
    if pretty and not (_MODEL_CODE_RE.match(pretty) and " " not in pretty):
        return pretty[:48]
    if os_name:
        low = os_name.lower()
        if "ios" in low or "iphone" in low:
            return "iPhone"
        if "android" in low:
            return "Android"
        return f"{os_name[:24]}"
    return f"Устройство {index + 1}"


def format_hwid_label(hwid: str, index: int = 0) -> str:
    return format_device_label({"hwid": hwid}, index)


def is_factory_model_code(name: str | None) -> bool:
    """True для кодов вроде 2407FPN8EG (не бренд-имя)."""
    s = (name or "").strip()
    return bool(s and _MODEL_CODE_RE.match(s) and " " not in s and not re.search(r"[a-z]", s))


def slot_price(slot_number: int) -> int:
    """Цена за конкретный слот (2 → 35, 3 → 40, …)."""
    if slot_number <= BASE_DEVICE_SLOTS:
        return 0
    return FIRST_EXTRA_SLOT_PRICE + (slot_number - 2) * EXTRA_SLOT_STEP


def cost_to_add_slots(current_limit: int, add: int) -> int:
    current = clamp_device_limit(current_limit)
    add = max(0, int(add))
    target = min(MAX_DEVICE_SLOTS, current + add)
    return sum(slot_price(slot) for slot in range(current + 1, target + 1))


def monthly_price_for_limit(limit: int) -> int:
    limit = clamp_device_limit(limit)
    return BASE_MONTHLY_PRICE + sum(slot_price(slot) for slot in range(2, limit + 1))


def monthly_price_for_user(user) -> int:
    return monthly_price_for_limit(user_device_limit(user))


def pack_price(device_limit: int, *, months: int = 1) -> int:
    months = max(1, int(months))
    return monthly_price_for_limit(device_limit) * months


def pack_plan_id(device_limit: int, *, months: int = 1) -> str:
    """Единый пакет: месяц доступа + целевой лимит устройств. Пример: 1m@d3."""
    limit = clamp_device_limit(device_limit)
    months = max(1, int(months))
    return f"{months}m@d{limit}"


def parse_pack_plan(plan_id: str | None) -> tuple[int, int] | None:
    """plan_id вида 1m@d3 → (months, device_limit)."""
    if not plan_id or "@d" not in plan_id:
        return None
    left, right = plan_id.split("@d", 1)
    if not left.endswith("m"):
        return None
    try:
        months = int(left[:-1])
        devices = int(right.strip())
    except ValueError:
        return None
    if months < 1 or months > 24:
        return None
    if devices < BASE_DEVICE_SLOTS or devices > MAX_DEVICE_SLOTS:
        return None
    return months, devices


def parse_device_addon_plan(plan_id: str | None) -> int | None:
    """plan_id вида dev+2 → сколько слотов докупить."""
    if not plan_id or not plan_id.startswith("dev+"):
        return None
    try:
        add = int(plan_id[4:].strip())
    except ValueError:
        return None
    if add < 1 or add > MAX_DEVICE_SLOTS:
        return None
    return add


def can_add_slots(user, add: int) -> bool:
    add = int(add)
    if add < 1:
        return False
    return user_device_limit(user) + add <= MAX_DEVICE_SLOTS


def addon_options(user) -> list[dict]:
    current = user_device_limit(user)
    options: list[dict] = []
    for add in range(1, MAX_DEVICE_SLOTS - current + 1):
        new_limit = current + add
        price = cost_to_add_slots(current, add)
        options.append(
            {
                "add": add,
                "new_limit": new_limit,
                "price_rub": price,
                "monthly_after": monthly_price_for_limit(new_limit),
                "plan_id": f"dev+{add}",
            }
        )
    return options


def pack_options(*, months: int = 1) -> list[dict]:
    options: list[dict] = []
    for limit in range(BASE_DEVICE_SLOTS, MAX_DEVICE_SLOTS + 1):
        options.append(
            {
                "devices": limit,
                "plan_id": pack_plan_id(limit, months=months),
                "price_rub": pack_price(limit, months=months),
                "monthly_rub": monthly_price_for_limit(limit),
            }
        )
    return options


def format_last_seen(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(str(raw).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m %H:%M")
    except ValueError:
        return ""
