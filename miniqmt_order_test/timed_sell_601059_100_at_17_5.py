from __future__ import annotations

import argparse
import ctypes
import datetime
import gc
import os
import sys
import time

from xtquant import xtconstant
from xtquant import xttrader
from xtquant.xttype import StockAccount


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


# ========== Windows timing/priority tuning (copied style from stock/pcclock/ptime.py) ==========
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)

HANDLE = ctypes.c_void_p
DWORD = ctypes.c_uint32
INT = ctypes.c_int
DWORD64 = ctypes.c_uint64

kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = HANDLE
kernel32.SetPriorityClass.argtypes = [HANDLE, DWORD]
kernel32.SetPriorityClass.restype = ctypes.c_bool
kernel32.GetCurrentThread.argtypes = []
kernel32.GetCurrentThread.restype = HANDLE
kernel32.SetThreadPriority.argtypes = [HANDLE, INT]
kernel32.SetThreadPriority.restype = ctypes.c_bool
kernel32.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
kernel32.QueryPerformanceCounter.restype = ctypes.c_bool
kernel32.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
kernel32.QueryPerformanceFrequency.restype = ctypes.c_bool
kernel32.SetProcessAffinityMask.argtypes = [HANDLE, DWORD64]
kernel32.SetProcessAffinityMask.restype = ctypes.c_bool
kernel32.SetThreadAffinityMask.argtypes = [HANDLE, DWORD64]
kernel32.SetThreadAffinityMask.restype = DWORD64

HIGH_PRIORITY_CLASS = 0x80
THREAD_PRIORITY_TIME_CRITICAL = 15
TIME_BEGIN_PERIOD = 1
CPU_MASK = DWORD64(0x00000001)

perf_freq = ctypes.c_uint64()
kernel32.QueryPerformanceFrequency(ctypes.byref(perf_freq))
PERF_FREQ = perf_freq.value


def init_system() -> None:
    try:
        winmm.timeBeginPeriod(TIME_BEGIN_PERIOD)
    except Exception:
        pass

    try:
        h_process = kernel32.GetCurrentProcess()
        kernel32.SetPriorityClass(h_process, HIGH_PRIORITY_CLASS)
        h_thread = kernel32.GetCurrentThread()
        kernel32.SetThreadPriority(h_thread, THREAD_PRIORITY_TIME_CRITICAL)
    except Exception:
        pass

    try:
        h_process = kernel32.GetCurrentProcess()
        h_thread = kernel32.GetCurrentThread()
        kernel32.SetProcessAffinityMask(h_process, CPU_MASK)
        kernel32.SetThreadAffinityMask(h_thread, CPU_MASK)
    except Exception:
        pass


def cleanup_system() -> None:
    try:
        winmm.timeEndPeriod(TIME_BEGIN_PERIOD)
    except Exception:
        pass


def _parse_at_time(at: str) -> datetime.time:
    s = str(at).strip()
    # allow: HH:MM:SS or HH:MM:SS.mmm or HH:MM:SS.ffffff
    if "." in s:
        hhmmss, frac = s.split(".", 1)
        base = datetime.datetime.strptime(hhmmss, "%H:%M:%S").time()
        frac = "".join(ch for ch in frac if ch.isdigit())
        frac = (frac + "000000")[:6]
        return datetime.time(base.hour, base.minute, base.second, int(frac))
    base = datetime.datetime.strptime(s, "%H:%M:%S").time()
    return base


def _target_epoch(at_time: datetime.time, date: datetime.date, *, next_day_if_passed: bool) -> float:
    target_dt = datetime.datetime.combine(date, at_time)
    target_ts = target_dt.timestamp()
    now_ts = time.time()
    if target_ts <= now_ts and next_day_if_passed:
        target_dt = target_dt + datetime.timedelta(days=1)
        target_ts = target_dt.timestamp()
    return target_ts


def wait_until_epoch(target_ts: float, *, coarse_lead_ms: int = 50) -> None:
    # coarse sleep: leave some time for busy spin
    while True:
        now_ts = time.time()
        remaining = target_ts - now_ts
        if remaining <= 0:
            break

        remaining_ms = remaining * 1000
        if remaining_ms > coarse_lead_ms + 5:
            # sleep most of the remaining time
            sleep_ms = int(remaining_ms - coarse_lead_ms)
            ctypes.windll.kernel32.Sleep(max(0, sleep_ms))
            continue

        # fine spin
        break

    while True:
        if time.time() >= target_ts:
            return


class Callback(xttrader.XtQuantTraderCallback):
    def on_order_error(self, order_error):
        print(_now(), "[cb] order_error:", order_error)


def main() -> int:
    # reduce runtime jitter
    gc.disable()
    os.environ["PYTHONHASHSEED"] = "0"

    ap = argparse.ArgumentParser()
    ap.add_argument("--qmt-path", default=r"F:\stock\qmt\userdata_mini")
    ap.add_argument("--account-id", default="31161458")
    ap.add_argument("--session", type=int, default=1)

    ap.add_argument("--at", default="14:40:01", help="target local time, e.g. 14:40:01 or 14:40:01.000")
    ap.add_argument("--date", default="", help="optional date YYYY-MM-DD (default today)")
    ap.add_argument("--next-day-if-passed", action="store_true", help="if target already passed, schedule next day")

    ap.add_argument("--live", action="store_true")
    ap.add_argument("--confirm", default="")

    ap.add_argument("--wait-after", type=float, default=1.0, help="seconds to keep process alive after submit")
    args = ap.parse_args()

    if args.live and args.confirm != "YES":
        print("Refusing to place live order: pass --confirm YES")
        return 2

    code = "601059.SH"
    volume = 100
    limit_price = 17.5

    at_time = _parse_at_time(args.at)
    if args.date:
        date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        date = datetime.date.today()

    target_ts = _target_epoch(at_time, date, next_day_if_passed=bool(args.next_day_if_passed))
    target_dt = datetime.datetime.fromtimestamp(target_ts)

    print(_now(), "target:", target_dt.strftime("%Y-%m-%d %H:%M:%S.%f"))

    cb = Callback()
    trader = xttrader.XtQuantTrader(args.qmt_path, args.session, cb)

    print(_now(), "starting trader...")
    trader.start()

    init_system()
    try:
        print(_now(), "connecting (warmup)...")
        trader.connect()
        account = StockAccount(args.account_id)

        print(_now(), f"armed: sell {volume} {code} @ {limit_price} (limit)")
        print(_now(), "waiting...")
        wait_until_epoch(target_ts)

        print(_now(), "TRIGGER")
        if not args.live:
            print(_now(), "dry-run: NOT placing any order")
            time.sleep(max(0.0, float(args.wait_after)))
            return 0

        order_id = trader.order_stock(
            account=account,
            stock_code=code,
            order_type=xtconstant.STOCK_SELL,
            order_volume=int(volume),
            price_type=xtconstant.FIX_PRICE,
            price=float(limit_price),
            strategy_name="timed_sell_601059_17_5",
            order_remark="timed",
        )
        print(_now(), "order_id:", order_id)
        time.sleep(max(0.0, float(args.wait_after)))
        return 0
    finally:
        cleanup_system()
        print(_now(), "stopping trader...")
        try:
            trader.stop()
        except Exception as e:
            print(_now(), "stop error:", e, file=sys.stderr)
        try:
            gc.enable()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
