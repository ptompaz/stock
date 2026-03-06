from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import gc
import os
import sys
import threading
import time
import re
import subprocess

from ntp_utils import sample_ntp_average

from xtquant import xtconstant
from xtquant import xttrader
from xtquant.xttype import StockAccount


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _fmt_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")


def _ping_windows_avg_rtt_ms(output: str):
    m = re.search(r"Average\s*=\s*(\d+)ms", output, flags=re.IGNORECASE)
    if m:
        return float(m.group(1))

    m = re.search(r"平均\s*=\s*(\d+)ms", output)
    if m:
        return float(m.group(1))

    times = [int(x) for x in re.findall(r"time[=<]\s*(\d+)ms", output, flags=re.IGNORECASE)]
    if times:
        return sum(times) / len(times)

    return None


def get_ping_rtt_half_ms(host: str, count: int, timeout_ms: int):
    try:
        from icmplib import ping as _icmp_ping
    except Exception as e:
        return {"success": False, "error": f"icmplib not available: {e}. Install with: pip install icmplib"}

    try:
        # Hard-coded sampling to reduce calibration delay:
        # 4 samples, every 100ms. (CLI --ping-count is ignored.)
        h = _icmp_ping(
            host,
            count=4,
            interval=0.1,
            timeout=max(0.001, float(timeout_ms) / 1000.0),
            privileged=False,
        )

        avg_rtt_ms = getattr(h, "avg_rtt", None)
        if avg_rtt_ms is None:
            return {"success": False, "error": "icmplib ping returned no avg_rtt"}

        try:
            avg_rtt_ms = float(avg_rtt_ms)
        except Exception:
            return {"success": False, "error": f"invalid avg_rtt: {avg_rtt_ms}"}

        if avg_rtt_ms <= 0:
            return {"success": False, "error": f"avg_rtt_ms<=0: {avg_rtt_ms}"}

        return {"success": True, "avg_rtt_ms": avg_rtt_ms, "rtt_half_ms": avg_rtt_ms / 2.0}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _obj_to_dict(obj) -> dict:
    if obj is None:
        return {}
    out = {}
    for k in dir(obj):
        if k.startswith("_"):
            continue
        try:
            v = getattr(obj, k)
        except Exception:
            continue
        if callable(v):
            continue
        if isinstance(v, (int, float, str, bool)) or v is None:
            out[k] = v
    return out


def _fmt_obj(obj) -> str:
    d = _obj_to_dict(obj)
    if d:
        try:
            return json.dumps(d, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(d)
    return str(obj)


# ========== Windows timing/priority tuning (based on stock/pcclock/ptime.py) ==========
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
kernel32.SetProcessAffinityMask.argtypes = [HANDLE, DWORD64]
kernel32.SetProcessAffinityMask.restype = ctypes.c_bool
kernel32.SetThreadAffinityMask.argtypes = [HANDLE, DWORD64]
kernel32.SetThreadAffinityMask.restype = DWORD64

HIGH_PRIORITY_CLASS = 0x80
THREAD_PRIORITY_TIME_CRITICAL = 15
TIME_BEGIN_PERIOD = 1
CPU_MASK = DWORD64(0x00000001)


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
    if "." in s:
        hhmmss, frac = s.split(".", 1)
        base = datetime.datetime.strptime(hhmmss, "%H:%M:%S").time()
        frac = "".join(ch for ch in frac if ch.isdigit())
        frac = (frac + "000000")[:6]
        return datetime.time(base.hour, base.minute, base.second, int(frac))
    base = datetime.datetime.strptime(s, "%H:%M:%S").time()
    return base


def _load_broker_advance_ms_for_date(date_str: str) -> Optional[float]:
    path = os.path.join(os.path.dirname(__file__), "broker_advance_ms.txt")
    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                if k.strip() != date_str:
                    continue
                try:
                    return float(v.strip())
                except Exception:
                    return None
    except Exception:
        return None
    return None


def _target_epoch(at_time: datetime.time, date: datetime.date, *, next_day_if_passed: bool) -> float:
    target_dt = datetime.datetime.combine(date, at_time)
    target_ts = target_dt.timestamp()
    now_ts = time.time()
    return target_ts


def wait_until_epoch(target_ts: float, *, coarse_lead_ms: int = 50) -> None:
    while True:
        now_ts = time.time()
        remaining = target_ts - now_ts
        if remaining <= 0:
            break

        remaining_ms = remaining * 1000
        if remaining_ms > coarse_lead_ms + 5:
            sleep_ms = int(remaining_ms - coarse_lead_ms)
            ctypes.windll.kernel32.Sleep(max(0, sleep_ms))
            continue
        break

    while True:
        if time.time() >= target_ts:
            return


def _order_type(side: str) -> int:
    s = str(side).strip().lower()
    if s in ("sell", "s"):
        return xtconstant.STOCK_SELL
    if s in ("buy", "b"):
        return xtconstant.STOCK_BUY
    raise ValueError(f"unknown side: {side}")


class Callback(xttrader.XtQuantTraderCallback):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._last_order_error = None
        self._last_order_error_ts = 0.0
        self._last_stock_order = None
        self._last_stock_order_ts = 0.0
        self._normal_order_event = threading.Event()

    def on_order_error(self, order_error):
        with self._lock:
            self._last_order_error = order_error
            self._last_order_error_ts = time.time()
        print(_now(), "[cb] order_error:", _fmt_obj(order_error))

    def on_stock_order(self, order):
        with self._lock:
            self._last_stock_order = order
            self._last_stock_order_ts = time.time()
            d = _obj_to_dict(order)
            status = d.get("order_status")
            if status is None:
                status = d.get("status")
            is_junk = False
            try:
                junk = getattr(xtconstant, "ORDER_JUNK", None)
                if junk is not None and status is not None:
                    is_junk = int(status) == int(junk)
            except Exception:
                is_junk = False
            if not is_junk:
                self._normal_order_event.set()

    def consume_last_error_since(self, since_ts: float):
        with self._lock:
            if self._last_order_error is None:
                return None
            if self._last_order_error_ts < since_ts:
                return None
            return self._last_order_error

    def consume_stock_order_since(self, since_ts: float):
        with self._lock:
            if self._last_stock_order is None:
                return None
            if self._last_stock_order_ts < since_ts:
                return None
            return self._last_stock_order

    def has_normal_order(self) -> bool:
        return self._normal_order_event.is_set()


def main() -> int:
    # reduce runtime jitter
    gc.disable()
    os.environ["PYTHONHASHSEED"] = "0"

    ap = argparse.ArgumentParser()
    ap.add_argument("--qmt-path", default=r"F:\stock\qmt\userdata_mini")
    ap.add_argument("--account-id", default="31161458")
    ap.add_argument("--session", type=int, default=1)

    ap.add_argument("--at", required=True, help="target local time, e.g. 14:40:01 or 14:40:01.500")
    ap.add_argument("--date", default="", help="optional date YYYY-MM-DD (default today)")

    ap.add_argument("--code", required=True, help="stock code like 601059.SH")
    ap.add_argument("--side", default="sell", choices=["buy", "sell"])
    ap.add_argument("--volume", type=int, required=True)
    ap.add_argument("--price", type=float, required=True, help="limit price")

    ap.add_argument("--retry-interval-ms", type=int, default=10)
    ap.add_argument("--retry-interval-ms2", type=int, default=20)
    ap.add_argument("--phase1-count", type=int, default=5)
    ap.add_argument("--retry-times", type=int, default=5)

    ap.add_argument("--calibrate", action="store_true", help="use NTP offset + broker ping RTT/2 to trigger earlier")
    ap.add_argument("--ntp-servers", default="ntp.aliyun.com,ntp1.aliyun.com")
    ap.add_argument("--ntp-samples", type=int, default=20)
    ap.add_argument("--ntp-timeout-ms", type=int, default=500)
    ap.add_argument("--broker-host", default="139.224.114.71")
    ap.add_argument("--ping-count", type=int, default=5)
    ap.add_argument("--ping-timeout-ms", type=int, default=50)

    ap.add_argument("--live", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--wait-after", type=float, default=1.0)
    args = ap.parse_args()

    if args.volume <= 0:
        print("volume must be > 0")
        return 2

    if not args.qmt_path or not os.path.isdir(args.qmt_path):
        print(_now(), "qmt-path directory not found or not accessible:", args.qmt_path)
        return 2

    if args.live and args.confirm != "YES":
        print("Refusing to place live order: pass --confirm YES")
        return 2

    at_time = _parse_at_time(args.at)
    if args.date:
        date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        date = datetime.date.today()

    target_ts = _target_epoch(at_time, date, next_day_if_passed=False)
    target_dt = datetime.datetime.fromtimestamp(target_ts)

    if time.time() >= target_ts:
        print(_now(), "target already passed, exiting without triggering:", target_dt.strftime("%Y-%m-%d %H:%M:%S.%f"))
        return 2

    print(_now(), "target:", target_dt.strftime("%Y-%m-%d %H:%M:%S.%f"))

    # If we have a precomputed daily broker delay, use it directly and skip ping/NTP.
    date_str = date.strftime("%Y-%m-%d")
    daily_advance_ms = _load_broker_advance_ms_for_date(date_str)

    # calibration: advance_ms = ntp_offset_ms + rtt_half_ms; adjusted_target = target - advance_ms
    advance_ms = 0.0
    if daily_advance_ms is not None:
        # NOTE: The persisted value represents broker clock lag vs local time (local - broker).
        # To land in the intended broker second, we should delay local trigger by this amount.
        delay_ms = float(daily_advance_ms)
        advance_ms = float(daily_advance_ms)
        adjusted_target_ts = target_ts + (delay_ms / 1000.0)
        print(
            _now(),
            f"delay_ms={delay_ms:.3f} (broker_advance_ms.txt {date_str}), adjusted_target={_fmt_ts(adjusted_target_ts)}",
        )
    elif args.calibrate:
        try:
            ping = get_ping_rtt_half_ms(args.broker_host, int(args.ping_count), int(args.ping_timeout_ms))
            if ping.get("success"):
                rtt_half_ms = float(ping["rtt_half_ms"])
                avg_rtt_ms = float(ping["avg_rtt_ms"])
                print(_now(), f"ping {args.broker_host}: avg_rtt_ms={avg_rtt_ms:.3f} rtt_half_ms={rtt_half_ms:.3f}")
            else:
                rtt_half_ms = 0.0
                print(_now(), f"ping {args.broker_host} failed: {ping.get('error')}")
        except Exception as e:
            rtt_half_ms = 0.0
            print(_now(), f"ping {args.broker_host} error:", e)

        try:
            servers = [s.strip() for s in str(args.ntp_servers).split(",") if s.strip()]
            ntp = sample_ntp_average(
                servers,
                samples=int(args.ntp_samples),
                timeout_s=float(args.ntp_timeout_ms) / 1000.0,
                max_workers=min(4, max(1, len(servers))),
            )
            if ntp.get("success"):
                # 口径：ntp_offset_ms>0 表示“本机时间比NTP早”，因此需要提前触发（target - ntp_offset_ms）。
                ntp_offset_ms = float(ntp["avg_local_minus_ntp_ms"])
                ntp_samples = int(ntp["samples"])
                ntp_rtt_ms = float(ntp["avg_rtt_ms"])
                print(
                    _now(),
                    f"ntp offset_ms={ntp_offset_ms:.3f} samples={ntp_samples} avg_rtt_ms={ntp_rtt_ms:.3f} servers={servers}",
                )
            else:
                ntp_offset_ms = 0.0
                print(_now(), f"ntp failed: {ntp.get('error')}")
        except Exception as e:
            ntp_offset_ms = 0.0
            print(_now(), "ntp error:", e)

        advance_ms = float(ntp_offset_ms + rtt_half_ms)
        adjusted_target_ts = target_ts - (advance_ms / 1000.0)
        print(
            _now(),
            f"advance_ms={advance_ms:.3f} (ntp_offset_ms + rtt_half_ms), adjusted_target={_fmt_ts(adjusted_target_ts)}",
        )
    else:
        adjusted_target_ts = target_ts

    cb = Callback()
    trader = xttrader.XtQuantTrader(args.qmt_path, args.session, cb)

    print(_now(), "starting trader...")
    trader.start()

    init_system()
    try:
        print(_now(), "connecting (warmup)...")
        trader.connect()
        account = StockAccount(args.account_id)

        print(
            _now(),
            f"armed: {args.side} {args.volume} {args.code} @ {args.price} (limit)",
        )
        print(_now(), "waiting...")
        if time.time() >= adjusted_target_ts:
            print(_now(), "adjusted target already passed, exiting without triggering:", _fmt_ts(adjusted_target_ts))
            return 2
        wait_until_epoch(adjusted_target_ts)

        print(_now(), "TRIGGER")
        if not args.live:
            print(_now(), "dry-run: NOT placing any order")
            time.sleep(max(0.0, float(args.wait_after)))
            return 0

        retry_interval_ms = max(1, int(args.retry_interval_ms))
        retry_times = max(1, int(args.retry_times))
        retry_interval_ms2 = max(1, int(args.retry_interval_ms2))
        phase1_count = max(0, int(args.phase1_count))

        prev_attempt_start_ts = None

        for attempt in range(1, retry_times + 1):
            if cb.has_normal_order():
                break

            attempt_start_ts = time.time()
            delta_ms = None
            if prev_attempt_start_ts is not None:
                delta_ms = (attempt_start_ts - prev_attempt_start_ts) * 1000.0
            prev_attempt_start_ts = attempt_start_ts
            try:
                print(_now(), f"attempt={attempt}/{retry_times} call_start")
                order_id = trader.order_stock(
                    account=account,
                    stock_code=args.code,
                    order_type=_order_type(args.side),
                    order_volume=int(args.volume),
                    price_type=xtconstant.FIX_PRICE,
                    price=float(args.price),
                    strategy_name="timed_order",
                    order_remark=f"timed_attempt_{attempt}",
                )
                call_end_ts = time.time()
                print(_now(), f"attempt={attempt}/{retry_times} call_end")
                call_ms = (call_end_ts - attempt_start_ts) * 1000.0
                if delta_ms is None:
                    print(_now(), f"attempt={attempt}/{retry_times} order_id:", order_id, f"call_ms={call_ms:.3f}")
                else:
                    print(
                        _now(),
                        f"attempt={attempt}/{retry_times} order_id:",
                        order_id,
                        f"call_ms={call_ms:.3f}",
                        f"delta_ms={delta_ms:.3f}",
                    )
            except Exception as e:
                print(_now(), f"attempt={attempt}/{retry_times} submit_error:", e)
                interval_ms = retry_interval_ms if attempt <= phase1_count else retry_interval_ms2
                elapsed_ms = (time.time() - attempt_start_ts) * 1000.0
                sleep_ms = max(0.0, interval_ms - elapsed_ms)
                if attempt < retry_times:
                    cb._normal_order_event.wait(timeout=sleep_ms / 1000.0)
                continue

            # If no valid order_id returned, keep retrying on the fixed interval.
            valid_order_id = True
            try:
                oid = int(order_id)
                valid_order_id = order_id is not None and oid != 0 and oid != -1
            except Exception:
                valid_order_id = False
            if not valid_order_id:
                print(_now(), f"attempt={attempt}/{retry_times} invalid order_id, retrying")

                # When order_id is invalid (e.g. -1), order_error callback is often the only place
                # to get the real reason. Wait a short time and print the latest error if any.
                err_deadline = time.time() + 0.05
                err = cb.consume_last_error_since(call_end_ts)
                while err is None and time.time() < err_deadline:
                    cb._normal_order_event.wait(timeout=0.001)
                    err = cb.consume_last_error_since(call_end_ts)
                if err is not None:
                    print(_now(), f"attempt={attempt}/{retry_times} order_error_for_invalid_order_id:", _fmt_obj(err))

                interval_ms = retry_interval_ms if attempt <= phase1_count else retry_interval_ms2
                elapsed_ms = (time.time() - attempt_start_ts) * 1000.0
                sleep_ms = max(0.0, interval_ms - elapsed_ms)
                if attempt < retry_times:
                    cb._normal_order_event.wait(timeout=sleep_ms / 1000.0)
                continue

            interval_ms = retry_interval_ms if attempt <= phase1_count else retry_interval_ms2
            elapsed_ms = (time.time() - attempt_start_ts) * 1000.0
            sleep_ms = max(0.0, interval_ms - elapsed_ms)
            if attempt < retry_times:
                cb._normal_order_event.wait(timeout=sleep_ms / 1000.0)

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
