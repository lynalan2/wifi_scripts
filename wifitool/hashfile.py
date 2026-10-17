"""Разбор файлов hashcat: .hc22000 и out-файлы с подобранными паролями.

Общий модуль для cracker (взлом) и hcx (захват) — раньше эта логика была
в двух местах в разном виде.

Формат строки .hc22000:
    WPA*<01|02>*MIC_или_PMKID*AP_MAC*CLIENT_MAC*ESSID_HEX*...
    01 = PMKID, 02 = EAPOL (рукопожатие).
"""


def decode_hex_essid(hex_str):
    """Декодирует ESSID из hex в строку ('' при ошибке)."""
    try:
        return bytes.fromhex(hex_str).decode("utf-8", errors="replace")
    except Exception:
        return ""


def essid_from_hash(line):
    """ESSID из строки WPA*..*..*..*..*ESSID_HEX*..  или None."""
    try:
        parts = line.split("*")
        if len(parts) > 5 and parts[5]:
            return bytes.fromhex(parts[5]).decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def read_hashes(path):
    """Непустые строки из .hc22000 (список)."""
    try:
        with open(path, "r", errors="ignore") as f:
            return [l.strip() for l in f if l.strip()]
    except Exception:
        return []


def decode_hashcat_plain(plain):
    """Если hashcat записал $HEX[...] — декодируем обратно в строку."""
    if plain.startswith("$HEX[") and plain.endswith("]"):
        try:
            return bytes.fromhex(plain[5:-1]).decode("utf-8", errors="replace")
        except Exception:
            return plain
    return plain


def parse_out_line(line, valid_essids):
    """
    Разбирает строку out-файла hashcat в (essid, password).

    Поддерживает три формата:
      1. -m 22000, --outfile-format по умолчанию: "WPA*02*...*ESSID_HEX*...:password".
      2. Старый -m 2500: "PMK:AP_MAC:STA_MAC:ESSID:password" (5 полей через ':').
      3. --outfile-format 2: только пароль (ESSID берём из .hc22000).
    Возвращает (essid|None, password) или None.
    """
    head = line.split(":", 1)[0]
    if head.startswith("WPA*") or head.count("*") >= 5:
        hash_part, sep, plain = line.partition(":")
        if not sep:
            return None
        return essid_from_hash(hash_part), decode_hashcat_plain(plain)

    parts = line.split(":", 4)
    if len(parts) >= 5 and all(parts[:4]):
        return parts[3], decode_hashcat_plain(parts[4])

    if ":" not in line:
        essid = next(iter(valid_essids)) if valid_essids else None
        return essid, decode_hashcat_plain(line)

    return None


def types_label(types):
    """Человекочитаемое описание типов хэша сети (множество '01'/'02'/...)."""
    parts = []
    if "02" in types:
        parts.append("EAPOL handshake")
    if "01" in types:
        parts.append("PMKID")
    for t in sorted(types - {"01", "02"}):
        parts.append(f"WPA*{t}")
    return ", ".join(parts) if parts else "?"


def parse_hc22000(path):
    """
    Разбирает .hc22000 по сетям.
    Возвращает {bssid: {"essid", "types": set, "lines": []}}.
    BSSID нормализуется в вид aa:bb:cc:dd:ee:ff.
    """
    import os
    nets = {}
    if not os.path.exists(path):
        return nets
    for line in read_hashes(path):
        p = line.split("*")
        if len(p) < 6 or p[0] != "WPA":
            continue
        htype = p[1]
        ap = p[3].lower()
        if len(ap) == 12 and all(c in "0123456789abcdef" for c in ap):
            bssid = ":".join(ap[i:i + 2] for i in range(0, 12, 2))
        else:
            bssid = ap
        essid = decode_hex_essid(p[5])

        net = nets.setdefault(bssid, {"essid": essid, "types": set(), "lines": []})
        net["types"].add(htype)
        net["lines"].append(line)
        if essid and not net["essid"]:
            net["essid"] = essid
    return nets
