from __future__ import annotations
import time
import json
import os
from datetime import datetime
from xtquant import xttrader, xtdata
from typing import Dict, Optional, Any

# ========== 核心配置（仅需修改这1项！） ==========
# QMT客户端实际目录（你提供的路径）
CLIENT_PATH = "F:\\stock\\qmt\\userdata_mini"
# 你的国金资金账号（纯数字，如123456789）
ACCOUNT_ID = "你的资金账号"

# 固定配置（无需修改）
BROKER_ID = "1069"  # 国金证券券商代码固定为1069
SESSION_NAME = "sell_300622_session"  # 会话名称（任意唯一字符串）

# ========== 工具函数 ==========
def _now_str() -> str:
    """获取当前时间字符串（毫秒级）"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def init_trader() -> Optional[xttrader.XtQuantTrader]:
    """初始化QMT交易客户端（适配新版xtquant）"""
    print(f"[{_now_str()}] 🚀 开始初始化交易客户端，路径：{CLIENT_PATH}")

    if not CLIENT_PATH or not os.path.isdir(CLIENT_PATH):
        print(f"[{_now_str()}] ❌ CLIENT_PATH 目录不存在或不可访问：{CLIENT_PATH}")
        print("🔍 请将 CLIENT_PATH 改为当前机器上 MiniQMT/QMT 的 userdata 目录（例如 ...\\userdata_mini）")
        return None
    
    try:
        # 修复：新版XtQuantTrader必须传入session参数
        trader = xttrader.XtQuantTrader(CLIENT_PATH, SESSION_NAME)
        
        # 启动交易线程（新版无需关注oldloop，内部已处理）
        ret = trader.start()
        if ret != 0:
            print(f"[{_now_str()}] ❌ 交易客户端启动失败，错误码：{ret}")
            print("🔍 排查方向：1. QMT客户端是否运行 2. 目录是否正确 3. 是否以管理员权限运行")
            return None
        
        # 修复：QMT已登录时，仅需账号+券商代码，无需密码
        print(f"[{_now_str()}] 📌 QMT已登录，尝试免密登录账号：{ACCOUNT_ID}")
        login_result = trader.login(
            user_id=ACCOUNT_ID,
            password="",  # 空密码（QMT已登录时无需填写）
            broker_id=BROKER_ID,
            xt_trader_path=CLIENT_PATH,
            session_id=SESSION_NAME
        )
        
        if login_result["success"]:
            print(f"[{_now_str()}] ✅ 免密登录成功！账号：{ACCOUNT_ID}")
            return trader
        else:
            error_msg = login_result['msg']
            error_code = login_result['error_code']
            print(f"[{_now_str()}] ❌ 登录失败：{error_msg}（错误码：{error_code}）")
            # 免密登录失败的解决方案
            error_tips = {
                1001: "QMT客户端未运行，请先打开并登录QMT",
                2002: "账号未在QMT登录，请先在QMT客户端登录你的账号",
                3003: "网络异常，请检查QMT客户端网络连接",
                4004: "目录权限不足，请以管理员权限运行代码"
            }
            if error_code in error_tips:
                print(f"💡 解决方案：{error_tips[error_code]}")
            trader.stop()
            return None
    
    except Exception as e:
        print(f"[{_now_str()}] ❌ 初始化交易客户端异常：{str(e)}")
        return None

def sell_stock(
    trader: xttrader.XtQuantTrader,
    stock_code: str,
    volume: int,
    price: Optional[float] = None
) -> Optional[str]:
    """
    卖出股票（300622 博士眼镜）
    :param trader: 已登录的交易实例
    :param stock_code: 股票代码（300622.SZ）
    :param volume: 卖出数量（200股）
    :param price: 卖出价格（None=使用最新价）
    :return: 委托编号/None
    """
    # 1. 校验卖出数量（A股必须是100的整数倍）
    if volume % 100 != 0:
        print(f"[{_now_str()}] ❌ 卖出数量错误：{volume}股，必须是100的整数倍")
        return None
    
    # 2. 标准化股票代码（确保是300622.SZ）
    if "." not in stock_code:
        stock_code = f"{stock_code}.SZ" if stock_code.startswith(("0", "3")) else f"{stock_code}.SH"
    
    # 3. 获取最新价（未指定价格时）
    if price is None:
        try:
            # 跳过历史数据下载（避免KeyboardInterrupt）
            xtdata.enable_hello = False  # 隐藏多余提示
            tick_data = xtdata.get_full_tick([stock_code])
            if not tick_data or stock_code not in tick_data:
                print(f"[{_now_str()}] ❌ 无法获取{stock_code}（博士眼镜）的最新行情")
                return None
            price = tick_data[stock_code]["lastPrice"]
            print(f"[{_now_str()}] 📈 {stock_code}（博士眼镜）最新价：{price:.2f}元，将以此价格卖出{volume}股")
        except Exception as e:
            print(f"[{_now_str()}] ❌ 获取行情失败：{str(e)}")
            return None
    
    # 4. 构建卖出委托参数
    order_params = {
        "stock_code": stock_code,
        "order_type": 2,        # 2=卖出（1=买入）
        "price_type": 2,        # 2=限价单（1=市价单，创业板慎用）
        "price": price,         # 委托价格
        "volume": volume,       # 卖出数量（200股）
        "account_id": ACCOUNT_ID,
        "strategy_name": "sell_300622"  # 策略名称，任意填写
    }
    
    # 5. 提交委托
    print(f"[{_now_str()}] 📤 提交卖出委托...")
    order_result = trader.order_stock(**order_params)
    
    if order_result["success"]:
        order_id = order_result["order_id"]
        print(f"[{_now_str()}] ✅ 委托提交成功！委托编号：{order_id}")
        return order_id
    else:
        error_msg = order_result['msg']
        error_code = order_result['error_code']
        print(f"[{_now_str()}] ❌ 委托失败：{error_msg}（错误码：{error_code}）")
        # 委托失败常见原因
        fail_tips = {
            2002: "可用持仓不足（请确认持有≥200股300622）",
            2003: "价格超出涨跌幅限制（创业板±20%）",
            2004: "非交易时间（A股交易时间：9:30-11:30/13:00-15:00）",
            2005: "无创业板交易权限（需去营业部开通）"
        }
        if error_code in fail_tips:
            print(f"💡 解决方案：{fail_tips[error_code]}")
        return None

def query_order_status(trader: xttrader.XtQuantTrader, order_id: str) -> Dict[str, Any]:
    """查询委托状态"""
    try:
        query_result = trader.query_stock_order(order_id=order_id, account_id=ACCOUNT_ID)
        if query_result["success"] and query_result["data"]:
            order_info = query_result["data"][0]
            # 委托状态映射
            status_map = {
                0: "未提交", 1: "已提交", 2: "部分成交",
                3: "全部成交", 4: "已撤销", 5: "撤销中", 6: "已拒绝"
            }
            order_info["status_desc"] = status_map.get(order_info["order_status"], "未知状态")
            return order_info
        else:
            print(f"[{_now_str()}] ❌ 查询委托失败：{query_result['msg']}")
            return {}
    except Exception as e:
        print(f"[{_now_str()}] ❌ 查询委托异常：{str(e)}")
        return {}

# ========== 主执行逻辑 ==========
if __name__ == "__main__":
    # 修复：禁用多余提示，避免下载历史数据导致中断
    xtdata.enable_hello = False
    # 跳过历史数据下载（解决KeyboardInterrupt）
    xtdata.download_sector_data = lambda: None  # 空实现，避免耗时下载
    
    # 初始化交易客户端
    trader = init_trader()
    if not trader:
        exit(1)
    
    try:
        # 执行卖出操作：300622.SZ（博士眼镜）200股
        stock_code = "300622.SZ"
        sell_volume = 200
        order_id = sell_stock(trader, stock_code, sell_volume)
        
        # 实时查询委托状态（直到成交/撤销/拒绝）
        if order_id:
            print(f"\n[{_now_str()}] 📋 委托状态跟踪（按Ctrl+C终止）：")
            while True:
                order_status = query_order_status(trader, order_id)
                if order_status:
                    traded_vol = order_status.get('traded_volume', 0)
                    print(f"[{_now_str()}] 状态：{order_status['status_desc']} | 已成交：{traded_vol}/{sell_volume}股")
                    # 终止条件：全部成交/已撤销/已拒绝
                    if order_status["order_status"] in [3, 4, 6]:
                        break
                time.sleep(2)  # 每2秒查询一次
    
    except KeyboardInterrupt:
        print(f"\n[{_now_str()}] ⏹️ 用户手动终止程序")
    except Exception as e:
        print(f"\n[{_now_str()}] ❌ 程序运行出错：{str(e)}")
    finally:
        # 安全退出（新版trader无需logout，stop即可）
        if trader:
            trader.stop()
            print(f"[{_now_str()}] ✅ 已安全退出交易客户端")