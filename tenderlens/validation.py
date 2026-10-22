"""Strict CSV boundary; this module has no database or UI dependencies."""
import csv
import io
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

from tenderlens.models import CSV_FIELDS, Item, ValidationError, ValidationReport

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_SQL_INTEGER = 2**63 - 1
MAX_PRICE = Decimal("92233720368547758.07")


def is_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and (parsed.port is None or 0 < parsed.port <= 65535)
                and parsed.username is None and parsed.password is None
                and "\\" not in value
                and not any(char.isspace() or ord(char) < 32 for char in value))
    except ValueError:
        return False


def _positive_int(value: str, field: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or len(value) > 19:
        raise ValueError(f"{field}: требуется положительное целое число")
    result = int(value)
    if not 0 < result <= MAX_SQL_INTEGER:
        raise ValueError(f"{field}: число вне допустимого диапазона")
    return result


def _parse(row: dict[str, str], dataset_kind: str) -> Item:
    required = [key for key in CSV_FIELDS if key != "source_url"]
    missing = [key for key in required if not row[key]]
    if missing:
        raise ValueError("Пустые обязательные поля: " + ", ".join(missing))
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["contract_date"]):
        raise ValueError("contract_date: требуется дата YYYY-MM-DD")
    try:
        contract_date = date.fromisoformat(row["contract_date"])
    except ValueError:
        raise ValueError("contract_date: несуществующая дата") from None
    values = dict(row)
    values["contract_date"] = contract_date
    for key in ("density_g_m2", "sheets_per_pack", "quantity"):
        values[key] = _positive_int(row[key], key)
    price = row["unit_price"]
    if len(price) > 24 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", price):
        raise ValueError("unit_price: положительная цена, точка и максимум два дробных знака")
    values["unit_price"] = Decimal(price)
    if not 0 < values["unit_price"] <= MAX_PRICE:
        raise ValueError("unit_price: цена вне допустимого диапазона")
    for key in ("paper_format", "currency"):
        values[key] = row[key].upper()
    for key in ("unit", "vat_basis", "delivery_basis"):
        values[key] = row[key].lower()
    allowed = {"paper_format": ("A3", "A4"), "unit": ("pack",), "currency": ("KZT",),
               "vat_basis": ("included", "excluded"), "delivery_basis": ("included", "excluded")}
    for key, options in allowed.items():
        if values[key] not in options:
            raise ValueError(f"{key}: допустимо {', '.join(options)}")
    if row["source_url"] and not is_https_url(row["source_url"]):
        raise ValueError("source_url: требуется корректная ссылка HTTPS")
    if dataset_kind == "real" and not row["source_url"]:
        raise ValueError("source_url: ссылка обязательна для реального набора")
    return Item(**values)


def validate_csv(content: bytes, dataset_kind: str = "synthetic") -> ValidationReport:
    if dataset_kind not in ("synthetic", "real"):
        raise ValueError("Тип набора должен быть synthetic или real")
    if len(content) > MAX_BYTES:
        raise ValueError("Файл больше 10 МиБ")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Требуется кодировка UTF-8") from None
    if "\x00" in text:
        raise ValueError("CSV содержит недопустимый нулевой символ")
    # The stdlib defaults to 128 KiB per field, below our documented file limit.
    csv.field_size_limit(MAX_BYTES)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader, [])
        headers = [name.strip() for name in headers]
        if len(headers) != len(set(headers)):
            raise ValueError("Повторяющиеся заголовки CSV")
        missing = [key for key in CSV_FIELDS if key not in headers]
        if missing:
            raise ValueError("Отсутствуют столбцы: " + ", ".join(missing))
        extra = [key for key in headers if key not in CSV_FIELDS]
        rows = []
        previous_line = reader.line_num
        for number, cells in enumerate(reader, start=1):
            if number > MAX_ROWS:
                raise ValueError("Файл содержит больше 5000 строк данных")
            values = dict(zip(headers, (cell.strip() for cell in cells)))
            rows.append((previous_line + 1, len(cells) == len(headers), values))
            previous_line = reader.line_num
    except csv.Error as exc:
        raise ValueError(f"Некорректный CSV: {exc}") from None
    counts = Counter(row.get("item_id", "") for _, _, row in rows)
    accepted, errors = [], []
    for line, correct_width, row in rows:
        item_id = row.get("item_id", "")
        try:
            if item_id and counts[item_id] > 1:
                raise ValueError("Повтор item_id: отклонены все строки с этим ID")
            if not correct_width:
                raise ValueError("Число значений не соответствует числу столбцов")
            accepted.append((line, _parse({key: row[key] for key in CSV_FIELDS}, dataset_kind)))
        except ValueError as exc:
            errors.append(ValidationError(line, item_id, str(exc)))
    contracts = {}
    inconsistent = set()
    for _, item in accepted:
        identity = (item.contract_date, item.buyer_id, item.supplier_id)
        if item.contract_id in contracts and contracts[item.contract_id] != identity:
            inconsistent.add(item.contract_id)
        contracts[item.contract_id] = identity
    items = []
    for line, item in accepted:
        if item.contract_id in inconsistent:
            errors.append(ValidationError(line, item.item_id,
                          f"contract_id {item.contract_id}: различаются дата договора, заказчик или поставщик; "
                          "все позиции конфликтующего договора отклонены"))
        else:
            items.append(item)
    warnings = ("Неизвестные столбцы проигнорированы: " + ", ".join(extra),) if extra else ()
    return ValidationReport(tuple(items), tuple(sorted(errors, key=lambda error: error.row_number)), warnings)
