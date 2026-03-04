import time
from datetime import datetime, timedelta
import concurrent.futures

from ntp_utils import get_ntp_core_data as _get_ntp_core_data

# 配置项
NTP_SERVERS = ["ntp.aliyun.com", "ntp1.aliyun.com"]  # 去掉cloudflare（延迟高）
CHECK_TIMES = 20
MAX_WORKERS = 2

def get_ntp_core_data(server):
    """只获取稳定可信的核心数据：总RTT + 真实偏移"""
    try:
        core = _get_ntp_core_data(server, timeout_s=0.5)
        if not core.get("success"):
            return {"server": server, "success": False, "error": core.get("error")}
        return {
            "server": server,
            "success": True,
            "总RTT(ms)": core["total_rtt_ms"],
            "真实偏移(ms)": core["offset_ms_raw"],
            "ntp_time": core["ntp_time"],
        }
    except Exception as e:
        return {"server": server, "success": False, "error": str(e)}

def calculate_ntp_offset():
    """20次检查，只输出稳定可信的核心数据"""
    check_results = []
    print(f"开始{CHECK_TIMES}次NTP检查（仅输出稳定数据）...\n")
    
    for check_idx in range(1, CHECK_TIMES + 1):
        print(f"=== 第{check_idx}次检查 ===")
        
        # 并行请求服务器
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(get_ntp_core_data, s) for s in NTP_SERVERS]
            server_results = [f.result() for f in futures]
        
        # 筛选有效结果
        valid_results = [r for r in server_results if r["success"]]
        if not valid_results:
            print("  所有服务器连接失败\n")
            continue
        
        # 输出核心数据（无失真）
        for res in valid_results:
            print(f"  服务器 {res['server']}: 总RTT={res['总RTT(ms)']}ms | 真实偏移={res['真实偏移(ms)']}ms")
        
        # 取偏移最小的结果
        best_result = min(valid_results, key=lambda x: abs(x["真实偏移(ms)"]))
        local_now = datetime.now()
        compensated_time = local_now - timedelta(milliseconds=best_result["真实偏移(ms)"])
        
        # 存储结果
        check_results.append({
            "检查次数": check_idx,
            "最优服务器": best_result["server"],
            "真实偏移(ms)": best_result["真实偏移(ms)"],
            "总RTT(ms)": best_result["总RTT(ms)"],
            "补偿后时间": compensated_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        })
        
        print(f"  本次最优：偏移={best_result['真实偏移(ms)']}ms | 补偿后时间={compensated_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}\n")

    # 统计核心结果
    valid_offsets = [r["真实偏移(ms)"] for r in check_results]
    valid_rtts = [r["总RTT(ms)"] for r in check_results]
    
    stats = {"错误": "无有效结果"} if not valid_offsets else {
        "总有效检查次数": len(valid_offsets),
        "偏移平均值(ms)": round(sum(valid_offsets)/len(valid_offsets), 3),
        "偏移波动范围(ms)": round(max(valid_offsets)-min(valid_offsets), 3),
        "RTT平均值(ms)": round(sum(valid_rtts)/len(valid_rtts), 3),
        "推荐补偿值(ms)": round(sorted(valid_offsets, key=lambda x: abs(x))[0], 3)  # 最稳定偏移
    }

    return {"统计结果": stats, "详细记录": check_results}

# 运行
if __name__ == "__main__":
    start = time.time()
    try:
        result = calculate_ntp_offset()
        print("="*70)
        print("=== 20次检查核心统计（金融交易可用） ===")
        for k, v in result["统计结果"].items():
            print(f"{k}: {v}")
        print(f"总耗时：{time.time()-start:.2f}秒")
        
        # 输出交易代码可用的补偿值
        if "推荐补偿值(ms)" in result["统计结果"]:
            print(f"\n【交易代码集成建议】使用补偿值：{result['统计结果']['推荐补偿值(ms)']}ms")
    except Exception as e:
        print(f"执行失败：{str(e)}")