# HDHiveSearch 插件修复设计文档 V2

**日期:** 2026-03-20
**问题:** 1) 命令处理器缺少去重机制 2) 插件图标更换

---

## 1. 问题概述

### 问题1: 命令处理器重复触发
- **现象:** 执行 `/hdhive_checkin` 时收到10条"权限不足"消息
- **原因:** 命令处理方法（`_handle_user_info`、`_handle_checkin`、`_handle_quota`）缺少去重机制，事件被多次触发时重复执行
- **参考:** 搜索请求已有 `_request_cache` 去重机制（3秒内相同关键词只处理一次）

### 问题2: 插件图标更换
- **现象:** 当前插件图标为 `ccv2.png`，需更换为 `Hdhive.png`
- **位置:** `__init__.py` 第21行 `plugin_icon = "ccv2.png"`

---

## 2. 修复方案

### 2.1 命令处理器去重机制

**修改文件:** `plugins.v2/hdhivesearch/__init__.py`

**修改位置:** `_handle_user_info`、`_handle_checkin`、`_handle_quota` 方法

**修改内容:**
在每个命令处理方法开头添加去重检查，使用现有的 `_request_cache` 字典：

```python
def _handle_user_info(self, channel, userid):
    """处理用户信息查询（Premium功能）"""
    # 去重检查：3秒内相同命令只处理一次
    cache_key = f"cmd:{userid}:me"
    current_time = time.time()
    last_time = self._request_cache.get(cache_key, 0)
    if current_time - last_time < 3:
        logger.debug(f"忽略重复命令: /hdhive_me")
        return
    self._request_cache[cache_key] = current_time

    if not self._check_premium_access("用户信息查询"):
        ...
```

**去重键命名:**
- `_handle_user_info` → `cmd:{userid}:me`
- `_handle_checkin` → `cmd:{userid}:checkin`
- `_handle_quota` → `cmd:{userid}:quota`
- `_handle_stats_query` → `cmd:{userid}:stats` (一并添加)

### 2.2 插件图标更换

**修改文件:** `plugins.v2/hdhivesearch/__init__.py`

**修改位置:** 第21行

**修改内容:**
```python
# 修改前
plugin_icon = "ccv2.png"

# 修改后
plugin_icon = "Hdhive.png"
```

---

## 3. 实施步骤

1. **添加命令去重机制**
   - 在 `_handle_user_info` 添加去重检查
   - 在 `_handle_checkin` 添加去重检查
   - 在 `_handle_quota` 添加去重检查
   - 在 `_handle_stats_query` 添加去重检查

2. **更换插件图标**
   - 修改 `plugin_icon = "Hdhive.png"`

3. **提交变更**

---

## 4. 影响范围

- **插件主模块:** `__init__.py`
  - `_handle_user_info` - 添加去重
  - `_handle_checkin` - 添加去重
  - `_handle_quota` - 添加去重
  - `_handle_stats_query` - 添加去重
  - `plugin_icon` - 更换图标
- **无破坏性变更:** 仅添加去重逻辑，不改变业务逻辑
