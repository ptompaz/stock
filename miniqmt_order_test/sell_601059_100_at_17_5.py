from __future__ import annotations

import argparse
import sys
import json
import threading
import time
from datetime import datetime

from xtquant import xtconstant
from xtquant import xttrader
from xtquant.xttype import StockAccount


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


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


class Callback(xttrader.XtQuantTraderCallback):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._last_order_error = None
        self._last_order_error_ts = 0.0

    def on_connected(self):
        print(_now(), "[cb] connected")

    def on_disconnected(self):
        print(_now(), "[cb] disconnected")

    def on_order_error(self, order_error):
        with self._lock:
            self._last_order_error = order_error
            self._last_order_error_ts = time.time()
        print(_now(), "[cb] order_error:", _fmt_obj(order_error))

    def consume_last_error_since(self, since_ts: float):
        with self._lock:
            if self._last_order_error is None:
                return None
            if self._last_order_error_ts < since_ts:
                return None
            return self._last_order_error

    def on_cancel_error(self, cancel_error):
        print(_now(), "[cb] cancel_error:", _fmt_obj(cancel_error))

    def on_stock_order(self, order):
        print(_now(), "[cb] stock_order:", _fmt_obj(order))

    def on_stock_trade(self, trade):
        print(_now(), "[cb] stock_trade:", _fmt_obj(trade))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qmt-path", default=r"F:\stock\qmt\userdata_mini")
    ap.add_argument("--session", type=int, default=1)
    ap.add_argument("--account-id", default="31161458")

    ap.add_argument("--live", action="store_true", help="actually place the order")
    ap.add_argument("--confirm", default="", help="must be YES when --live")
    ap.add_argument("--wait", type=float, default=2.0)
    ap.add_argument("--error-wait-ms", type=int, default=1000)
    args = ap.parse_args()

    if args.live and args.confirm != "YES":
        print("Refusing to place live order: pass --confirm YES")
        return 2

    code = "601059.SH"
    side = "sell"
    volume = 100
    limit_price = 18.5

    cb = Callback()
    trader = xttrader.XtQuantTrader(args.qmt_path, args.session, cb)

    print(_now(), "starting trader...")
    trader.start()

    try:
        print(_now(), "connecting...")
        trader.connect()

        account = StockAccount(args.account_id)

        print(_now(), f"intent: {side} {volume} {code} @ {limit_price} (limit)")

        if not args.live:
            print(_now(), "dry-run: not placing any order")
            time.sleep(max(0.0, float(args.wait)))
            return 0

        print(_now(), "LIVE order placing...")
        submit_start_ts = time.time()
        order_id = trader.order_stock(
            account=account,
            stock_code=code,
            order_type=xtconstant.STOCK_SELL,
            order_volume=int(volume),
            price_type=xtconstant.FIX_PRICE,
            price=float(limit_price),
            strategy_name="sell_601059_17_5",
            order_remark="miniqmt_order_test",
        )
        submit_end_ts = time.time()
        print(_now(), "order_id:", order_id)

        valid_order_id = True
        try:
            oid = int(order_id)
            valid_order_id = order_id is not None and oid != 0 and oid != -1
        except Exception:
            valid_order_id = False

        if not valid_order_id:
            err_deadline = time.time() + (max(1, int(args.error_wait_ms)) / 1000.0)
            err = cb.consume_last_error_since(submit_start_ts)
            while err is None and time.time() < err_deadline:
                time.sleep(0.001)
                err = cb.consume_last_error_since(submit_start_ts)
            if err is not None:
                print(_now(), "order_error_for_invalid_order_id:", _fmt_obj(err))
            else:
                print(_now(), "no on_order_error received for invalid order_id within error_wait_ms;可能是同步拒单无回调或回调延迟")

        time.sleep(max(0.0, float(args.wait)))

        return 0
    finally:
        print(_now(), "stopping trader...")
        try:
            trader.stop()
        except Exception as e:
            print(_now(), "stop error:", e, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
