# 共享常量定义，避免魔法值散布在代码中

# 命中次数
SINGLE_HIT = 1

# Core Magic 道具 ID
CORE_MAGIC_ITEM_IDS = frozenset({104001, 104002, 104003, 104004, 104007})

# 事件调度器策略
EXPLICIT_FIFO_EXPERIMENT = "explicit_fifo_experiment"

# 订阅执行限制检查
MIN_SUBSCRIPTION_ORDER = None  # None 表示无顺序要求
