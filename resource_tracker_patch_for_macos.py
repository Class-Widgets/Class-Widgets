# resource_tracker_patch.py
"""
Monkey patch for macOS resource_tracker bug in multiprocessing.shared_memory.
⚠️ 注意：这个补丁会禁用 resource_tracker 对共享内存的自动清理。
你需要在业务逻辑里手动调用 shm.unlink() 来释放资源。
"""

from multiprocessing import resource_tracker

# 保存原始方法
_orig_register = resource_tracker.register
_orig_unregister = resource_tracker.unregister


def _safe_register(name, rtype):
    # 跳过 shared_memory 的登记
    if rtype == "shared_memory":
        return None
    return _orig_register(name, rtype)


def _safe_unregister(name, rtype):
    # 跳过 shared_memory 的注销
    if rtype == "shared_memory":
        return None
    return _orig_unregister(name, rtype)


# 应用 monkey patch
resource_tracker.register = _safe_register
resource_tracker.unregister = _safe_unregister

print("⚠️ resource_tracker monkey patch applied: shared_memory will not be auto-cleaned")
