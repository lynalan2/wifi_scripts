"""Тесты чистых функций wifitool.hcx.

Разбор вывода hcxpcapngtool — это формат .hc22000, и hcx делает его через
hashfile.parse_hc22000 (покрыт в test_hashfile.py). Здесь проверяем:
  - _safe_name: ESSID/BSSID -> безопасное имя файла (чистая функция);
  - что hcx действительно использует hashfile.parse_hc22000 на реальном образце.
"""

from wifitool.hcx import _safe_name, _parse_hc22000

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    """Абсолютный путь к образцу из tests/fixtures/."""
    return str(FIXTURES / name)


# ---- _safe_name ----

def test_safe_name_basic():
    assert _safe_name("MyNet", "00:11:22:33:44:55") == "MyNet_001122334455.hc22000"


def test_safe_name_sanitizes_special_chars():
    # всё, кроме [a-zA-Z0-9-_.], заменяется на "_"
    assert _safe_name("My/Net Wi-Fi!", "AA:BB:CC:DD:EE:FF") == "My_Net_Wi-Fi__AABBCCDDEEFF.hc22000"


def test_safe_name_empty_essid_becomes_hidden():
    assert _safe_name("", "00:11:22:33:44:55") == "hidden_001122334455.hc22000"


def test_safe_name_truncates_long_essid_to_32():
    long_essid = "A" * 50
    name = _safe_name(long_essid, "00:11:22:33:44:55")
    base = name.split("_0011")[0]
    assert len(base) == 32


# ---- hcx использует hashfile.parse_hc22000 для вывода hcxpcapngtool ----

def test_hcx_parses_hcxpcapngtool_output_via_hashfile():
    # hcxpcapngtool пишет .hc22000 — разбираем тем же парсером
    nets = _parse_hc22000(fixture("hc22000_sample.hc22000"))
    assert set(nets) == {"00:11:22:33:44:55", "aa:bb:cc:dd:ee:ff"}
    assert nets["00:11:22:33:44:55"]["types"] == {"01", "02"}
