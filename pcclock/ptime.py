import ctypes
import datetime
import os
import time  # 修复：新增time模块导入
# 禁用Python的垃圾回收、JIT等额外开销
import gc

# 编译优化：禁用Python的断言和调试
__debug__ = False
# 强制使用静态内存分配
ctypes.CDLL("msvcrt.dll").malloc.restype = ctypes.c_void_p

gc.disable()  # 关闭垃圾回收
os.environ['PYTHONHASHSEED'] = '0'  # 固定哈希种子，减少随机开销

# ========== 修复：兼容64位Windows的句柄/参数类型 ==========
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
winmm = ctypes.WinDLL('winmm', use_last_error=True)

# 修复：手动定义Windows类型，兼容32/64位系统
HANDLE = ctypes.c_void_p
DWORD = ctypes.c_uint32
INT = ctypes.c_int
DWORD64 = ctypes.c_uint64  # 新增64位整数类型

# 重新定义Windows API参数类型（修复参数溢出问题）
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
# 修复：SetProcessAffinityMask参数类型（64位系统需用DWORD64）
kernel32.SetProcessAffinityMask.argtypes = [HANDLE, DWORD64]
kernel32.SetProcessAffinityMask.restype = ctypes.c_bool
kernel32.SetThreadAffinityMask.argtypes = [HANDLE, DWORD64]
kernel32.SetThreadAffinityMask.restype = DWORD64

# 常量定义
HIGH_PRIORITY_CLASS = 0x80
THREAD_PRIORITY_TIME_CRITICAL = 15
TIME_BEGIN_PERIOD = 1  # 0.1ms分辨率
CPU_MASK = DWORD64(0x00000001)  # 修复：用DWORD64封装CPU核心掩码

# 初始化硬件计时器
perf_freq = ctypes.c_uint64()
kernel32.QueryPerformanceFrequency(ctypes.byref(perf_freq))
PERF_FREQ = perf_freq.value

def init_system():
    """一次性完成所有系统优化（增加容错）"""
    try:
        # 1. 设置定时器分辨率
        winmm.timeBeginPeriod(TIME_BEGIN_PERIOD)
        print("✅ 定时器分辨率已设为0.1ms")
    except Exception as e:
        print(f"⚠️ 定时器分辨率设置失败：{e}")

    try:
        # 2. 提升进程+线程优先级
        hProcess = kernel32.GetCurrentProcess()
        kernel32.SetPriorityClass(hProcess, HIGH_PRIORITY_CLASS)
        hThread = kernel32.GetCurrentThread()
        kernel32.SetThreadPriority(hThread, THREAD_PRIORITY_TIME_CRITICAL)
        print("✅ 进程/线程优先级已提升为高+时间关键")
    except Exception as e:
        print(f"⚠️ 优先级设置失败（需管理员权限）：{e}")

    try:
        # 3. 锁定进程到单个CPU核心（修复参数溢出）
        kernel32.SetProcessAffinityMask(hProcess, CPU_MASK)
        kernel32.SetThreadAffinityMask(hThread, CPU_MASK)
        print("✅ 进程已绑定到CPU0核心")
    except Exception as e:
        print(f"⚠️ CPU核心绑定失败：{e}")

def ultra_precise_sync():
    init_system()
    count = 0
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    
    try:
        while True:
            # ========== 1. 计算目标时间 ==========
            now_ts = time.time()  # 修复：简化time.time()调用
            next_second = float(int(now_ts) + 1)
            wait_us = int((next_second - now_ts) * 1_000_000)
            
            # 跳过极短等待
            if wait_us < 100:
                ctypes.windll.kernel32.Sleep(1)
                continue
            
            # ========== 2. 粗sleep阶段 ==========
            sleep_us = wait_us - 20000  # 留20ms精校
            sleep_deviation_us = 0
            if sleep_us > 100:
                sleep_start = ctypes.c_uint64()
                sleep_end = ctypes.c_uint64()
                kernel32.QueryPerformanceCounter(ctypes.byref(sleep_start))
                ctypes.windll.kernel32.Sleep(int(sleep_us / 1000))
                kernel32.QueryPerformanceCounter(ctypes.byref(sleep_end))
                actual_sleep_us = (sleep_end.value - sleep_start.value) * 1_000_000 / PERF_FREQ
                sleep_deviation_us = actual_sleep_us - sleep_us
            
            # ========== 3. 精校循环 ==========
            while True:
                remaining = next_second - time.time()
                if remaining <= 0.0:
                    break
            
            # ========== 4. 计算偏差 ==========
            trigger_ts = time.time()
            final_deviation_ms = (trigger_ts - next_second) * 1000
            
            # ========== 5. 输出 ==========
            count += 1
            current_time = datetime.datetime.now()
            print(f"第{count:3d}次 | 时间：{current_time.strftime(fmt)} | 粗sleep偏差：{sleep_deviation_us/1000:.3f}ms | 最终偏差：{final_deviation_ms:.3f}ms")
            
    except KeyboardInterrupt:
        print("\n🛑 程序被手动终止")
    finally:
        # 恢复系统设置
        try:
            winmm.timeEndPeriod(TIME_BEGIN_PERIOD)
            gc.enable()
            print("✅ 已恢复系统默认设置")
        except:
            pass

if __name__ == "__main__":
    print("🚀 Python终极优化版启动（建议管理员权限运行）")
    print("-" * 100)
    ultra_precise_sync()