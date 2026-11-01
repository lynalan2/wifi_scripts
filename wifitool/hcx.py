#!/usr/bin/env python3
"""
Захват handshake/PMKID через hcxdumptool + валидация через hcxpcapngtool.

Идея:
  - пользователь задаёт число прогонов и длительность каждого;
  - каждый прогон эквивалентен:
        sudo timeout <dur> hcxdumptool -i <iface> -w capture_N.pcapng --rds=1
  - после прогона pcapng прогоняется через hcxpcapngtool -> .hc22000.
    hcxpcapngtool записывает в .hc22000 ТОЛЬКО то, что валидно для hashcat
    (корректные пары EAPOL / PMKID), поэтому сам факт появления строки =
    хэш пригоден для перебора в `hashcat -m 22000`. Так скрипт сам определяет,
    у каких сетей пойман правильный для hashcat handshake, ещё до вывода.
  - сети дедуплицируются по BSSID: если handshake сети уже сохранён в одном из
    прошлых прогонов, повторно (та же сеть) он не сохраняется.
"""

import subprocess
import tempfile
import shutil
from pathlib import Path

from wifitool.hashfile import parse_hc22000 as _parse_hc22000, types_label as _types_label
from wifitool.i18n import t
from wifitool.system import missing_tools


# ============ Утилиты ============

def _check_tools():
    """Возвращает список недостающих утилит."""
    return [t for t in ("hcxdumptool", "hcxpcapngtool", "timeout")
            if shutil.which(t) is None]


def _safe_name(essid, bssid):
    base = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in essid)[:32]
    base = base or "hidden"
    return f"{base}_{bssid.replace(':', '')}.hc22000"


def _ask_int(prompt, default, minimum=1):
    raw = input(prompt).strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v >= minimum else default
    except ValueError:
        return default


def _final_summary(seen, saved, dup_skips):
    print(f"\n{'=' * 60}")
    print(t("hcx.summary"))
    print(f"{'=' * 60}")
    if not seen:
        print(t("hcx.sum_none"))
        return

    print(t("hcx.sum_nets", n=len(seen)))
    print(t("hcx.sum_saved", s=len(saved), d=dup_skips))
    print()
    print("{:<22} {:<18} {:<20} {:<8} {}".format(
        "ESSID", "BSSID", t("hcx.col_type"), t("hcx.col_runs"), t("hcx.col_file")))
    print("-" * 100)
    for bssid, rec in seen.items():
        essid = (rec["essid"] or t("common.hidden"))[:20]
        label = _types_label(rec["types"])[:18]
        runs_str = ",".join(str(n) for n in sorted(rec["runs"]))
        path = str(saved[bssid]["path"]) if bssid in saved else t("hcx.not_saved")
        print("{:<22} {:<18} {:<20} {:<8} {}".format(
            essid, bssid, label, runs_str, path))
    print()
    print(t("hcx.hint"))


# ============ Основной сценарий ============

def hcxdumptool_flow(interface):
    missing = _check_tools()
    if missing:
        print(t("common.tools_missing", tools=", ".join(missing)))
        print(t("hcx.install"))
        return

    print(t("hcx.title"))
    runs = _ask_int(t("hcx.ask_runs"), 1)
    dur = _ask_int(t("hcx.ask_dur"), 60)

    print(t("hcx.iface", v=interface))
    print(t("hcx.runs", v=runs))
    print(t("hcx.cmd", d=dur, i=interface))

    # Готовые .hc22000 сохраняем туда, откуда запущена программа.
    save_dir = Path.cwd()

    tmp_dir = Path(tempfile.mkdtemp(prefix="hcxdump_"))
    saved = {}       # bssid -> {"essid", "path", "run", "types"}
    seen = {}        # bssid -> {"essid", "types": set, "runs": set}
    dup_skips = 0

    try:
        for i in range(1, runs + 1):
            print(f"\n{'=' * 60}")
            print(t("hcx.run_hdr", i=i, n=runs, d=dur))
            print(f"{'=' * 60}")

            capture = tmp_dir / f"capture_{i}.pcapng"
            try:
                # stdout/stderr наследуются — видно живой вывод --rds. timeout
                # завершит hcxdumptool по истечении dur (код возврата 124 — норма).
                subprocess.run(
                    ["timeout", str(dur), "hcxdumptool",
                     "-i", interface, "-w", str(capture), "--rds=1"]
                )
            except KeyboardInterrupt:
                print(t("hcx.run_interrupted"))

            if not capture.exists() or capture.stat().st_size == 0:
                print(t("hcx.empty", i=i))
                continue

            # hcxpcapngtool отфильтровывает всё, что непригодно для hashcat.
            hc_out = tmp_dir / f"capture_{i}.hc22000"
            subprocess.run(
                ["hcxpcapngtool", "-o", str(hc_out), str(capture)],
                capture_output=True, text=True
            )
            nets = _parse_hc22000(hc_out)

            if not nets:
                print(t("hcx.none_valid", i=i))
                continue

            print(t("hcx.run_found", i=i, n=len(nets)))
            for bssid, info in nets.items():
                rec = seen.setdefault(
                    bssid, {"essid": info["essid"], "types": set(), "runs": set()})
                rec["types"] |= info["types"]
                rec["runs"].add(i)
                if info["essid"] and not rec["essid"]:
                    rec["essid"] = info["essid"]

                essid = info["essid"] or t("common.hidden")
                label = _types_label(info["types"])

                if bssid in saved:
                    dup_skips += 1
                    print(t("hcx.dup", essid=essid, bssid=bssid, label=label, run=saved[bssid]["run"]))
                    continue

                dest = save_dir / _safe_name(essid, bssid)
                try:
                    dest.write_text("\n".join(info["lines"]) + "\n")
                except Exception as e:
                    print(t("hcx.save_fail", essid=essid, bssid=bssid, label=label, e=e))
                    continue
                saved[bssid] = {"essid": essid, "path": dest,
                                "run": i, "types": set(info["types"])}
                print(t("hcx.saved", essid=essid, bssid=bssid, label=label, dest=dest))

        _final_summary(seen, saved, dup_skips)

    except KeyboardInterrupt:
        print(t("common.interrupted"))
        _final_summary(seen, saved, dup_skips)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
