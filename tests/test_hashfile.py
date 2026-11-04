"""Тесты парсеров hashcat-файлов (wifitool.hashfile).

Чистые функции: .hc22000 / вывод hashcat -> структуры. Без root/железа.
"""

from wifitool.hashfile import (
    decode_hex_essid,
    essid_from_hash,
    decode_hashcat_plain,
    parse_out_line,
    types_label,
    parse_hc22000,
    read_hashes,
)

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    """Абсолютный путь к образцу из tests/fixtures/."""
    return str(FIXTURES / name)


# ---- decode_hex_essid ----

def test_decode_hex_essid_valid():
    assert decode_hex_essid("4d794e6574") == "MyNet"


def test_decode_hex_essid_invalid_returns_empty():
    assert decode_hex_essid("zz") == ""
    assert decode_hex_essid("abc") == ""     # нечётная длина


# ---- essid_from_hash ----

def test_essid_from_hash_valid_line():
    line = "WPA*02*" + "a" * 32 + "*001122334455*bbbbbbbbbbbb*4d794e6574*x*00"
    assert essid_from_hash(line) == "MyNet"


def test_essid_from_hash_too_few_fields_returns_none():
    assert essid_from_hash("WPA*02*deadbeef") is None


# ---- decode_hashcat_plain ($HEX[...]) ----

def test_decode_plain_hex():
    assert decode_hashcat_plain("$HEX[70617373]") == "pass"


def test_decode_plain_passthrough():
    assert decode_hashcat_plain("normalpass") == "normalpass"


def test_decode_plain_bad_hex_passthrough():
    # не распарсить как hex -> возвращаем как есть
    assert decode_hashcat_plain("$HEX[zz]") == "$HEX[zz]"


# ---- parse_out_line: формат -m 22000 (по умолчанию) ----

def test_out_line_22000_plain():
    lines = read_hashes(fixture("hashcat_out_22000.txt"))
    assert parse_out_line(lines[0], {"MyNet"}) == ("MyNet", "Secret123")


def test_out_line_22000_hex_password():
    lines = read_hashes(fixture("hashcat_out_22000.txt"))
    assert parse_out_line(lines[1], {"MyNet"}) == ("MyNet", "pass")


# ---- parse_out_line: старый формат -m 2500 ----

def test_out_line_2500_password_with_colon():
    lines = read_hashes(fixture("hashcat_out_2500.txt"))
    # пароль "pa:ss" содержит двоеточие — не должен обрезаться
    assert parse_out_line(lines[0], {"MyNet"}) == ("MyNet", "pa:ss")


def test_out_line_2500_empty_essid_current_behaviour():
    # ВАЖНО: строка 2500 с пустым ESSID сейчас возвращает None (пароль теряется).
    # Это помеченная находка — см. заметку в PR/чате. Тест фиксирует текущее
    # поведение, чтобы фикс был осознанным изменением.
    lines = read_hashes(fixture("hashcat_out_2500.txt"))
    assert parse_out_line(lines[1], {"MyNet"}) is None


# ---- parse_out_line: --outfile-format 2 (только пароль) ----

def test_out_line_plain_uses_known_essid():
    lines = read_hashes(fixture("hashcat_out_plain.txt"))
    assert parse_out_line(lines[0], {"MyNet"}) == ("MyNet", "JustThePassword")


def test_out_line_plain_without_known_essid():
    lines = read_hashes(fixture("hashcat_out_plain.txt"))
    assert parse_out_line(lines[0], set()) == (None, "JustThePassword")


# ---- parse_out_line: битые строки -> None ----

def test_out_line_wpa_hash_without_password_is_none():
    hash_only = "WPA*02*" + "a" * 32 + "*001122334455*bbbbbbbbbbbb*4d794e6574*x*00"
    assert parse_out_line(hash_only, {"MyNet"}) is None


def test_out_line_two_colon_fields_is_none():
    assert parse_out_line("a:b", {"MyNet"}) is None


# ---- types_label ----

def test_types_label_variants():
    assert types_label({"02"}) == "EAPOL handshake"
    assert types_label({"01"}) == "PMKID"
    assert types_label({"01", "02"}) == "EAPOL handshake, PMKID"
    assert types_label(set()) == "?"


# ---- parse_hc22000 ----

def test_hc22000_merges_duplicate_bssid_and_drops_broken():
    nets = parse_hc22000(fixture("hc22000_sample.hc22000"))
    # 2 сети (битые строки отброшены; дубль BSSID слит)
    assert set(nets) == {"00:11:22:33:44:55", "aa:bb:cc:dd:ee:ff"}


def test_hc22000_bssid_is_normalized():
    nets = parse_hc22000(fixture("hc22000_sample.hc22000"))
    assert "00:11:22:33:44:55" in nets          # 001122334455 -> aa:bb:...


def test_hc22000_merged_network_has_both_types():
    nets = parse_hc22000(fixture("hc22000_sample.hc22000"))
    ap1 = nets["00:11:22:33:44:55"]
    assert ap1["types"] == {"01", "02"}          # EAPOL + PMKID
    assert len(ap1["lines"]) == 2
    assert ap1["essid"] == "MyNet"


def test_hc22000_broken_lines_excluded():
    nets = parse_hc22000(fixture("hc22000_sample.hc22000"))
    # ни у одной сети не должно быть "битых" строк среди lines
    for net in nets.values():
        for line in net["lines"]:
            assert line.startswith("WPA*")
            assert len(line.split("*")) >= 6


def test_hc22000_hidden_essid_filled_from_later_line():
    nets = parse_hc22000(fixture("hc22000_hidden.hc22000"))
    assert nets["00:11:22:33:44:55"]["essid"] == "MyNet"
    assert len(nets["00:11:22:33:44:55"]["lines"]) == 2


def test_hc22000_nonexistent_file_returns_empty():
    assert parse_hc22000("/no/such/file-xyz.hc22000") == {}
