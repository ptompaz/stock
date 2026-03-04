from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from xtquant import xtconstant
from xtquant import xttrader
from xtquant.xttype import StockAccount


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


class Callback(xttrader.XtQuantTraderCallback):
    def on_connected(self):
        print(_now(), "[cb] connected")

    def on_disconnected(self):
        print(_now(), "[cb] disconnected")

    def on_order_error(self, order_error):
        print(_now(), "[cb] order_error:", order_error)

    def on_cancel_error(self, cancel_error):
        print(_now(), "[cb] cancel_error:", cancel_error)

    def on_stock_order(self, order):
        print(_now(), "[cb] stock_order:", order)

    def on_stock_trade(self, trade):
        print(_now(), "[cb] stock_trade:", trade)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qmt-path", default=r"F:\stock\qmt\userdata_mini")
    ap.add_argument("--session", type=int, default=1)
    ap.add_argument("--account-id", default="31161458")

    ap.add_argument("--live", action="store_true", help="actually place the order")
    ap.add_argument("--confirm", default="", help="must be YES when --live")
    ap.add_argument("--wait", type=float, default=2.0)
    args = ap.parse_args()

    if args.live and args.confirm != "YES":
        print("Refusing to place live order: pass --confirm YES")
        return 2

    code = "601059.SH"
    side = "sell"
    volume = 100
    limit_price = 17.5

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
        print(_now(), "order_id:", order_id)

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
