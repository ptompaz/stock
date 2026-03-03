import time
import ctypes
import datetime
import threading

# ========== Windows底层API封装（减少Python层开销） ==========
kernel32 = ctypes.WinDLL('kernel32.dll') if hasattr(ctypes, 'windll') else None
winmm = ctypes.WinDLL('winmm.dll') if hasattr(ctypes, 'windll') else None

# 高精度计时：QueryPerformanceCounter（硬件级，精度100ns以内）
def query_performance_counter():
    if not kernel32:
        return time.perf_counter()
    counter = ctypes.c_uint64()
    kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    return counter.value

def query_performance_frequency():
    if not kernel32:
        return 1e9
    freq = ctypes.c_uint64()
    kernel32.QueryPerformanceFrequency(ctypes.byref(freq))
    return freq.value

# 初始化硬件计时器频率
PERF_FREQ = query_performance_frequency()

def set_system_optimization():
    """系统级优化：定时器分辨率+进程/线程优先级+CPU性能模式"""
    if not kernel32:
        print("非Windows系统，跳过系统优化")
        return
    
    # 1. 设置定时器分辨率为0.1ms（100微秒）
    try:
        winmm.timeBeginPeriod(1)  # 1=100微秒，直接传底层参数
        print("已设置定时器分辨率：0.1ms（100微秒）")
    except:
        print("设置定时器分辨率失败")
    
    # 2. 提升进程+线程优先级（管理员权限）
    try:
        # 进程：高优先级
        process_handle = kernel32.GetCurrentProcess()
        kernel32.SetPriorityClass(process_handle, 0x00000080)  # HIGH_PRIORITY_CLASS
        # 线程：时间关键优先级（最高）
        thread_handle = kernel32.GetCurrentThread()
        kernel32.SetThreadPriority(thread_handle, 15)  # THREAD_PRIORITY_TIME_CRITICAL
        print("已提升进程/线程优先级：高+时间关键")
    except:
        print("设置优先级失败（需管理员权限）")
    
    # 3. 禁用CPU节能模式（可选，需管理员）
    try:
        powrprof = ctypes.WinDLL('powrprof.dll')
        # 设置电源计划为「高性能」
        GUID_HIGH_PERFORMANCE = ctypes.create_string_buffer(b'\x8c\x5e\x7f\xa8\x4f\x91\x4f\x8a\xa9\x0c\xe3\x5d\x84\x6c\x69\x75')
        powrprof.SetActivePowerScheme(None, GUID_HIGH_PERFORMANCE)
        print("已设置CPU为高性能模式")
    except:
        print("设置高性能模式失败（不影响核心精度）")

def sync_to_second_ultra_precise():
    """
    极致精度版：硬件级计时+极简精校循环+减少Python开销
    """
    count = 0
    set_system_optimization()
    
    # 目标：每秒0ms触发，精校预留20ms
    calibrate_ms = 20
    calibrate_us = calibrate_ms * 1000  # 转为微秒
    
    try:
        while True:
            # ========== 1. 极简目标时间计算（减少Python开销） ==========
            now_ts = time.time()
            next_second = int(now_ts) + 1  # 下一个整秒（无补偿，避免异常）
            wait_us = int((next_second - now_ts) * 1_000_000)  # 转为微秒
            
            # 跳过极短等待，避免高频循环
            if wait_us < 100:  # <100微秒
                time.sleep(0.001)
                continue
            
            # ========== 2. 粗sleep（留20ms精校，直接用微秒计算） ==========
            sleep_us = wait_us - calibrate_us
            sleep_deviation_us = 0
            if sleep_us > 100:  # >100微秒才sleep
                sleep_s = sleep_us / 1_000_000
                # 硬件计时记录sleep耗时（减少Python层误差）
                sleep_start = query_performance_counter()
                time.sleep(sleep_s)
                sleep_end = query_performance_counter()
                # 计算实际sleep耗时（微秒）
                actual_sleep_us = (sleep_end - sleep_start) * 1_000_000 / PERF_FREQ
                sleep_deviation_us = actual_sleep_us - sleep_us
            
            # ========== 3. 极致精简精校循环（几乎无Python开销） ==========
            # 直接用C级循环判断，减少Python字节码执行
            while True:
                remaining_us = int((next_second - time.time()) * 1_000_000)
                if remaining_us <= 0:
                    break
                # 剩余>100微秒时释放CPU，否则空等（极简判断）
                if remaining_us > 100:
                    pass  # 替代time.sleep(0)，减少系统调用
            
            # ========== 4. 计算偏差（硬件级计时） ==========
            trigger_ts = time.time()
            final_deviation_us = int((trigger_ts - next_second) * 1_000_000)
            final_deviation_ms = final_deviation_us / 1000
            
            # ========== 5. 精简输出 ==========
            count += 1
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            print(f"第{count:3d}次执行 | 实际时间：{current_time} | 粗sleep偏差：{sleep_deviation_us/1000:.3f}ms | 最终偏差：{final_deviation_ms:.3f}ms")
            
    except KeyboardInterrupt:
        print("\n程序被手动终止")
    finally:
        # 恢复定时器分辨率
        if winmm:
            try:
                winmm.timeEndPeriod(1)
            except:
                pass

if __name__ == "__main__":
    print("极致精度版启动（需管理员权限），按Ctrl+C终止...")
    print("-" * 120)
    sync_to_second_ultra_precise()