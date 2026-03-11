from __future__ import annotations

import argparse
from datetime import datetime

from xtquant import xttrader
from xtquant.xttype import StockAccount

from qmt_config import get_qmt_path


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _pick(obj, keys: list[str]):
    for k in keys:
        if hasattr(obj, k):
            try:
                return getattr(obj, k)
            except Exception:
                pass
    return None


def _to_row(o) -> dict:
    return {
        "order_id": _pick(o, ["order_id", "orderId", "entrust_id", "entrustId", "order_sysid", "orderSysid"]),
        "code": _pick(o, ["stock_code", "stockCode", "symbol"]),
        "side": _pick(o, ["order_type", "orderType"]),
        "price": _pick(o, ["price", "order_price", "orderPrice"]),
        "volume": _pick(o, ["order_volume", "volume", "orderVolume"]),
        "traded": _pick(o, ["traded_volume", "trade_volume", "tradedVolume"]),
        "status": _pick(o, ["order_status", "status", "orderStatus"]),
        "order_time": _pick(o, ["order_time", "orderTime", "insert_time", "insertTime", "entrust_time", "entrustTime"]),
        "report_time": _pick(o, ["report_time", "reportTime", "exchange_report_time", "exchangeReportTime"]),
        "exchange_time": _pick(o, ["exchange_time", "exchangeTime", "exch_time", "exchTime"]),
        "trade_time": _pick(o, ["trade_time", "tradeTime", "deal_time", "dealTime"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qmt-path", default=get_qmt_path())
    ap.add_argument("--account-id", default="31161458")
    ap.add_argument("--session", type=int, default=1)
    ap.add_argument("--cancelable-only", action="store_true")
    args = ap.parse_args()

    trader = xttrader.XtQuantTrader(args.qmt_path, args.session)

    print(_now(), "starting trader...")
    trader.start()
    try:
        print(_now(), "connecting...")
        trader.connect()

        account = StockAccount(args.account_id)
        orders = trader.query_stock_orders(account, cancelable_only=bool(args.cancelable_only))

        rows = []
        if isinstance(orders, (list, tuple)):
            for o in orders:
                rows.append(_to_row(o))
        print(_now(), f"orders_today count={len(rows)} cancelable_only={bool(args.cancelable_only)}")
        for r in rows:
            print(r)
        return 0
    finally:
        print(_now(), "stopping trader...")
        trader.stop()


if __name__ == "__main__":
    raise SystemExit(main())
