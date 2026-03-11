from __future__ import annotations

import argparse
import datetime
import os
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Tuple

from qmt_config import get_qmt_path

from ntp_utils import sample_ntp_average

from xtquant import xtconstant
from xtquant import xttrader
from xtquant.xttype import StockAccount


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _fmt_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")


def _obj_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _obj_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_obj_to_dict(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: _obj_to_dict(v) for k, v in vars(obj).items()}
    return str(obj)


def wait_until_epoch(target_ts: float, *, coarse_lead_ms: int = 50) -> None:
    while True:
        now_ts = time.time()
        remaining = target_ts - now_ts
        if remaining <= 0:
            break

        remaining_ms = remaining * 1000.0
        if remaining_ms > coarse_lead_ms + 5:
            sleep_ms = int(remaining_ms - coarse_lead_ms)
            time.sleep(max(0.0, sleep_ms / 1000.0))
            continue

        # busy wait in the last ~50ms
        while time.time() < target_ts:
            pass
        break


def _side_to_order_type(side: str) -> int:
    s = str(side).strip().lower()
    if s == "buy":
        return xtconstant.STOCK_BUY
    if s == "sell":
        return xtconstant.STOCK_SELL
    raise ValueError(f"unknown side: {side}")


def _round_step(ms: int, step_ms: int) -> int:
    if step_ms <= 1:
        return int(ms)
    return int((int(ms) // step_ms) * step_ms)


def _ceil_to_next_second(dt: datetime.datetime, *, add_seconds: int) -> datetime.datetime:
    d = dt + datetime.timedelta(seconds=add_seconds)
    if d.microsecond:
        d = d.replace(microsecond=0) + datetime.timedelta(seconds=1)
    return d


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()

    # Defaults aligned with timed_order.py usage
    ap.add_argument("--qmt-path", default=get_qmt_path())
    ap.add_argument("--account-id", default="31161458")
    ap.add_argument("--session", type=int, default=1)

    ap.add_argument("--code", default="601995.SH")
    ap.add_argument("--side", default="buy", choices=["buy", "sell"])
    ap.add_argument("--volume", type=int, default=100)
    ap.add_argument("--price", type=float, default=1.0)

    ap.add_argument("--live", action="store_true")
    ap.add_argument("--confirm", default="")

    ap.add_argument("--interval-sec", type=float, default=1.0, help="seconds between each live order")
    ap.add_argument("--lead-sec", type=int, default=2, help="schedule each test this many seconds in the future")

    ap.add_argument("--step-ms", type=int, default=5)
    ap.add_argument("--max-orders", type=int, default=100)
    ap.add_argument("--rounds", type=int, default=1, help="repeat the whole estimate multiple times and report median")

    ap.add_argument("--query-timeout-ms", type=int, default=3000)
    ap.add_argument("--cancel-after", action="store_true", help="try cancel after capturing order_time")

    ap.add_argument("--ignore-ntp", action="store_true", help="skip NTP sampling (local_minus_ntp_ms=0)")

    ap.add_argument("--ntp-servers", default="ntp.aliyun.com,ntp1.aliyun.com")
    ap.add_argument("--ntp-samples", type=int, default=20)
    ap.add_argument("--ntp-timeout-ms", type=int, default=500)

    return ap.parse_args()


def _query_order_time_by_id(
    trader: xttrader.XtQuantTrader,
    account: StockAccount,
    order_id: int,
    timeout_ms: int,
) -> Optional[int]:
    deadline = time.time() + max(0, int(timeout_ms)) / 1000.0
    while time.time() < deadline:
        try:
            orders = trader.query_stock_orders(account, cancelable_only=False)
        except Exception:
            orders = None
        if orders:
            for o in orders:
                try:
                    oid = int(getattr(o, "order_id", 0) or 0)
                except Exception:
                    oid = 0
                if oid == int(order_id):
                    try:
                        ot = getattr(o, "order_time", None)
                        if ot is None:
                            return None
                        return int(ot)
                    except Exception:
                        return None
        time.sleep(0.05)
    return None


def _estimate_one_round(
    trader: xttrader.XtQuantTrader,
    account: StockAccount,
    *,
    code: str,
    side: str,
    volume: int,
    price: float,
    lead_sec: int,
    interval_sec: float,
    step_ms: int,
    max_orders: int,
    query_timeout_ms: int,
    cancel_after: bool,
    local_minus_ntp_ms: float,
) -> Dict[str, Any]:
    # Binary search for the boundary offset within [0, hi_ms)ms, expanding hi_ms if needed.
    lo_ms = 0
    hi_ms = 1000
    max_hi_ms = 5000

    records: List[Dict[str, Any]] = []

    def do_test(offset_ms: int) -> Tuple[bool, Dict[str, Any]]:
        base_dt = _ceil_to_next_second(datetime.datetime.now(), add_seconds=int(lead_sec))
        base_epoch = base_dt.timestamp()
        target_epoch = base_epoch + (float(offset_ms) / 1000.0)
        expected_sec = int(target_epoch)

        print(
            _now(),
            f"test offset_ms={offset_ms} expected_sec={expected_sec} target={base_dt.strftime('%H:%M:%S')}.{offset_ms:03d} local_target={_fmt_ts(target_epoch)}",
        )

        wait_until_epoch(target_epoch)

        submit_start_ts = time.time()
        print(_now(), f"order_call_start local={_fmt_ts(submit_start_ts)}")
        order_id = trader.order_stock(
            account=account,
            stock_code=code,
            order_type=_side_to_order_type(side),
            order_volume=int(volume),
            price_type=xtconstant.FIX_PRICE,
            price=float(price),
            strategy_name="estimate_broker_ntp_offset",
            order_remark=f"offset_ms_{offset_ms}",
        )
        submit_end_ts = time.time()
        call_ms = (submit_end_ts - submit_start_ts) * 1000.0
        print(_now(), f"order_call_end local={_fmt_ts(submit_end_ts)} call_ms={call_ms:.3f} order_id={order_id}")

        ok_order_id = False
        try:
            ok_order_id = order_id is not None and int(order_id) > 0
        except Exception:
            ok_order_id = False

        rec: Dict[str, Any] = {
            "offset_ms": int(offset_ms),
            "base_epoch": base_epoch,
            "target_epoch": target_epoch,
            "expected_sec": expected_sec,
            "submit_start_ts": submit_start_ts,
            "submit_end_ts": submit_end_ts,
            "call_ms": float(call_ms),
            "order_id": order_id,
            "order_id_ok": ok_order_id,
        }

        if not ok_order_id:
            rec["error"] = "invalid_order_id"
            return False, rec

        order_time_sec = _query_order_time_by_id(trader, account, int(order_id), timeout_ms=query_timeout_ms)
        rec["order_time_sec"] = order_time_sec

        if order_time_sec is not None:
            try:
                broker_dt = datetime.datetime.fromtimestamp(int(order_time_sec))
                print(_now(), f"broker_order_time_sec={int(order_time_sec)} broker_time={broker_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception:
                print(_now(), f"broker_order_time_sec={order_time_sec}")

        if cancel_after:
            try:
                trader.cancel_order_stock(account, int(order_id))
                rec["cancel_requested"] = True
            except Exception as e:
                rec["cancel_requested"] = False
                rec["cancel_error"] = str(e)

        if order_time_sec is None:
            rec["error"] = "order_time_not_found"
            return False, rec

        # Compare broker second to local expected second for this test.
        is_expected_or_later = int(order_time_sec) >= int(expected_sec)

        # Estimate broker_minus_ntp_ms at submit_start time (coarse; order_time is seconds).
        ntp_ts_at_submit_start = submit_start_ts - (local_minus_ntp_ms / 1000.0)
        rec["local_minus_ntp_ms"] = float(local_minus_ntp_ms)
        rec["broker_minus_ntp_ms_est"] = (float(order_time_sec) - ntp_ts_at_submit_start) * 1000.0
        rec["delta_sec"] = int(order_time_sec) - int(expected_sec)
        rec["is_expected_or_later"] = is_expected_or_later

        print(
            _now(),
            f"judge expected_sec={expected_sec} broker_order_time_sec={int(order_time_sec)} delta_sec={int(order_time_sec) - int(expected_sec)}",
        )

        return is_expected_or_later, rec

    orders_used = 0

    # Expand hi_ms until it succeeds (or hit max_hi_ms).
    while True:
        ok, rec = do_test(int(hi_ms - step_ms))
        records.append(rec)
        orders_used += 1
        time.sleep(max(0.0, float(interval_sec)))

        if rec.get("order_id_ok") and rec.get("order_time_sec") is not None and ok:
            break
        if hi_ms >= max_hi_ms:
            break
        hi_ms = min(max_hi_ms, hi_ms + 1000)

    while hi_ms - lo_ms > step_ms and orders_used < int(max_orders):
        mid = (lo_ms + hi_ms) // 2
        mid = int(_round_step(mid, step_ms))
        if mid <= lo_ms:
            mid = lo_ms + step_ms
        if mid >= hi_ms:
            mid = hi_ms - step_ms

        ok, rec = do_test(mid)
        records.append(rec)
        orders_used += 1

        if not rec.get("order_id_ok") or rec.get("order_time_sec") is None:
            # If a test fails due to infra issues, keep some spacing and retry by shrinking budget.
            time.sleep(max(0.0, float(interval_sec)))
            continue

        if ok:
            hi_ms = mid
        else:
            lo_ms = mid

        time.sleep(max(0.0, float(interval_sec)))

    # Verification: require 3 consecutive successes; if failed, increase offset by step_ms and continue.
    final_offset_ms = int(hi_ms)
    consecutive_ok = 0
    verify_attempts = 0
    verify_needed = 3

    while consecutive_ok < verify_needed and orders_used < int(max_orders):
        verify_attempts += 1
        ok, rec = do_test(int(final_offset_ms))
        rec["verify"] = True
        rec["verify_attempt"] = verify_attempts
        rec["final_offset_ms"] = int(final_offset_ms)
        records.append(rec)
        orders_used += 1

        if rec.get("order_id_ok") and rec.get("order_time_sec") is not None and ok:
            consecutive_ok += 1
        else:
            consecutive_ok = 0
            final_offset_ms += int(step_ms)
            print(_now(), f"verify failed, bump offset by step_ms={step_ms} -> {final_offset_ms}")

        time.sleep(max(0.0, float(interval_sec)))

    result = {
        "code": code,
        "side": side,
        "volume": volume,
        "price": price,
        "step_ms": step_ms,
        "orders_used": orders_used,
        "offset_ms_est": int(final_offset_ms),
        "records": records,
    }
    return result


def _median_int(xs: List[int]) -> Optional[int]:
    ys = sorted(int(x) for x in xs)
    if not ys:
        return None
    return ys[len(ys) // 2]


def _advance_file_path() -> str:
    return os.path.join(os.path.dirname(__file__), "broker_advance_ms.txt")


def _load_advance_file(path: str) -> Dict[str, int]:
    data: Dict[str, int] = {}
    if not os.path.isfile(path):
        return data
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip()
                if not k:
                    continue
                try:
                    data[k] = int(float(v))
                except Exception:
                    continue
    except Exception:
        return data
    return data


def _save_advance_file(path: str, data: Dict[str, int]) -> None:
    items = sorted(data.items(), key=lambda kv: kv[0])
    with open(path, "w", encoding="utf-8") as f:
        for k, v in items:
            f.write(f"{k}={int(v)}\n")


def main() -> int:
    args = _parse_args()

    if not os.path.isdir(args.qmt_path):
        print(_now(), f"ERROR: qmt-path not found: {args.qmt_path}")
        return 2

    if args.live and args.confirm != "YES":
        print(_now(), "Refusing to place live order: pass --confirm YES")
        return 2

    if args.volume <= 0:
        print(_now(), "volume must be > 0")
        return 2

    if args.step_ms <= 0 or args.step_ms > 500:
        print(_now(), "step_ms must be in (0,500]")
        return 2

    if args.ignore_ntp:
        local_minus_ntp_ms = 0.0
        print(_now(), "ntp ignored: local_minus_ntp_ms=0")
    else:
        servers = [s.strip() for s in str(args.ntp_servers).split(",") if s.strip()]
        ntp = sample_ntp_average(
            servers,
            samples=int(args.ntp_samples),
            timeout_s=float(args.ntp_timeout_ms) / 1000.0,
            max_workers=min(4, max(1, len(servers))),
        )
        if ntp.get("success"):
            local_minus_ntp_ms = float(ntp["avg_local_minus_ntp_ms"])
            print(
                _now(),
                f"ntp local_minus_ntp_ms={local_minus_ntp_ms:.3f} samples={ntp.get('samples')} avg_rtt_ms={ntp.get('avg_rtt_ms')}",
            )
        else:
            local_minus_ntp_ms = 0.0
            print(_now(), f"ntp failed: {ntp.get('error')}")

    cb = xttrader.XtQuantTraderCallback()
    trader = xttrader.XtQuantTrader(args.qmt_path, int(args.session), cb)

    print(_now(), "starting trader...")
    trader.start()
    try:
        print(_now(), "connecting...")
        trader.connect()

        account = StockAccount(args.account_id)

        if not args.live:
            print(_now(), "DRY-RUN: add --live --confirm YES to actually place orders")
            return 0

        offsets: List[int] = []
        all_rounds: List[Dict[str, Any]] = []

        for r in range(max(1, int(args.rounds))):
            print(_now(), f"round {r + 1}/{int(args.rounds)}")
            res = _estimate_one_round(
                trader,
                account,
                code=args.code,
                side=args.side,
                volume=int(args.volume),
                price=float(args.price),
                lead_sec=int(args.lead_sec),
                interval_sec=float(args.interval_sec),
                step_ms=int(args.step_ms),
                max_orders=int(args.max_orders),
                query_timeout_ms=int(args.query_timeout_ms),
                cancel_after=bool(args.cancel_after),
                local_minus_ntp_ms=float(local_minus_ntp_ms),
            )
            all_rounds.append(res)
            offsets.append(int(res["offset_ms_est"]))

            # Wait a little before next round
            time.sleep(max(0.0, float(args.interval_sec)))

        med = _median_int(offsets)
        print(_now(), f"offset_ms_estimates={offsets} median={med} step_ms={args.step_ms}")

        if med is not None:
            path = _advance_file_path()
            data = _load_advance_file(path)
            today = datetime.date.today().strftime("%Y-%m-%d")
            data[today] = int(med)
            _save_advance_file(path, data)
            print(_now(), f"saved broker advance to {path}: {today}={int(med)}")

        print(_now(), "done")
        return 0
    finally:
        print(_now(), "stopping trader...")
        try:
            trader.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
