"""Тесты парсера CSV airodump-ng (wifitool.netscan.parse_airodump_csv).

Чистая функция: путь к CSV -> список сетей. Без root/адаптера/Wi-Fi.
"""

from wifitool.netscan import parse_airodump_csv, _power_to_int

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    """Абсолютный путь к образцу из tests/fixtures/."""
    return str(FIXTURES / name)


def _by_bssid(networks):
    return {n["bssid"]: n for n in networks}


# ---- базовый разбор ----

def test_basic_fields_parsed():
    nets = parse_airodump_csv(fixture("airodump_sample.csv"))
    ap = _by_bssid(nets)["AA:BB:CC:DD:EE:FF"]
    assert ap["channel"] == "6"
    assert ap["essid"] == "MyNet"
    assert ap["privacy"] == "WPA2"
    assert ap["power"] == "-40"


def test_sample_network_count():
    # 4 валидных AP в образце (строка станций не считается сетью)
    nets = parse_airodump_csv(fixture("airodump_sample.csv"))
    assert len(nets) == 4


# ---- скрытый ESSID ----

def test_hidden_essid_is_empty_string():
    nets = _by_bssid(parse_airodump_csv(fixture("airodump_sample.csv")))
    assert nets["11:22:33:44:55:66"]["essid"] == ""


# ---- лишние пробелы в полях обрезаются ----

def test_fields_are_stripped():
    nets = _by_bssid(parse_airodump_csv(fixture("airodump_sample.csv")))
    spaced = nets["22:33:44:55:66:77"]
    assert spaced["essid"] == "Spaced Name"   # внешние пробелы убраны
    assert spaced["channel"] == "1"           # "1 " -> "1"


# ---- запятая внутри ESSID ----
# airodump-ng не экранирует запятые в CSV, поэтому ESSID "Comma,Inside"
# разрежется по запятой и до нас дойдёт только "Comma". Это ограничение
# формата airodump, а не нашего кода — фиксируем текущее поведение.
def test_comma_inside_essid_is_truncated_by_airodump_format():
    nets = _by_bssid(parse_airodump_csv(fixture("airodump_sample.csv")))
    assert nets["33:44:55:66:77:88"]["essid"] == "Comma"


# ---- секция станций после секции AP ----

def test_station_section_marks_network_with_clients():
    nets = _by_bssid(parse_airodump_csv(fixture("airodump_sample.csv")))
    assert nets["AA:BB:CC:DD:EE:FF"]["has_stations"] is True
    # у сети без своей станции флаг False
    assert nets["11:22:33:44:55:66"]["has_stations"] is False


# ---- пустой / обрезанный CSV ----

def test_empty_csv_returns_empty_list():
    assert parse_airodump_csv(fixture("airodump_empty.csv")) == []


def test_header_only_csv_returns_empty_list():
    # только заголовок, без строк данных
    assert parse_airodump_csv(fixture("airodump_header_only.csv")) == []


def test_missing_bssid_column_returns_empty_list():
    assert parse_airodump_csv(fixture("airodump_no_bssid.csv")) == []


def test_nonexistent_file_returns_empty_list():
    assert parse_airodump_csv("/no/such/file-xyz.csv") == []


# ---- дубликат BSSID ----
# Текущее поведение: дубли BSSID в CSV дают две записи (airodump обычно их не
# выдаёт; дедуп для сканера не делается). Фиксируем как есть.
def test_duplicate_bssid_yields_two_entries():
    nets = parse_airodump_csv(fixture("airodump_dup_bssid.csv"))
    assert len(nets) == 2
    assert {n["bssid"] for n in nets} == {"AA:BB:CC:DD:EE:FF"}


# ---- helper _power_to_int ----

def test_power_to_int_valid_and_invalid():
    assert _power_to_int("-40") == -40
    assert _power_to_int("") == -999      # пустое -> в самый низ сортировки
    assert _power_to_int("n/a") == -999
    assert _power_to_int(None) == -999
