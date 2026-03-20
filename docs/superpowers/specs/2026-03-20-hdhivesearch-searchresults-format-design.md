# HDHiveSearch 搜索结果格式优化设计文档

**日期:** 2026-03-20
**问题:** 搜索结果抬头重复、资源列表行距密集、分隔符不一致

---

## 1. 问题概述

### 问题1: 搜索结果抬头重复
- **现象:** 搜索结果消息同时在 title 和 message body 中包含 "🔍 搜索结果 - 关键词"
- **原因:** `_handle_search` 第732行传入 title + `_format_search_results` 第811行又添加了相同标题
- **示例:**
  ```
  🔍 搜索结果 - 出走的决心  ← 来自 title
  🔍 搜索结果 - 出走的决心  ← 来自 message body (重复!)
  ━━━━━━━━━━━━━━
  ① 115 | ...
  ```

### 问题2: 资源列表行距密集
- **现象:** 每行资源直接相连，没有视觉分隔
- **原因:** `_format_search_results` 使用 `\n` 直接连接各行
- **示例:**
  ```
  ① 115 | ... | 💰1积分
  ② 115 | ... | 💰4积分  ← 紧密连接，阅读困难
  ③ 115 | ... | 💰4积分
  ```

### 问题3: 分隔符不一致
- **现象:** 有些标题（remark字段）包含换行符，导致格式错乱
- **原因:** API返回的 `remark` 字段可能包含 `\n` 字符
- **示例:**
  ```
  ⑨ 115 | 逐玉 (2026) S01.1080p.NF.WEB-DL.DDP.5.1.H.264
  01-23 | 10.45GB | ...  ← 换行导致分隔不一致
  ```

---

## 2. 修复方案

### 2.1 修复标题重复

**修改文件:** `plugins.v2/hdhivesearch/__init__.py`

**修改位置:** `_format_search_results` 方法（第810-850行）

**修改内容:**
- 移除 `lines = [f"🔍 搜索结果 - {keyword}", "━━━━━━━━━━━━━━"]` 中的标题行
- 保留分隔线和资源列表，标题统一由调用方通过 title 参数传入

```python
# 修改前 (第810-811行)
def _format_search_results(self, keyword: str, resources: List[Dict]) -> str:
    lines = [f"🔍 搜索结果 - {keyword}", "━━━━━━━━━━━━━━"]

# 修改后
def _format_search_results(self, resources: List[Dict]) -> str:
    lines = ["━━━━━━━━━━━━━━"]
```

**对应修改:** 调用方 `_handle_search` 第731-732行
```python
# 无需修改，title 参数保持不变
message = self._format_search_results(sorted_resources)
self._send_message(channel, userid, f"🔍 搜索结果 - {keyword}", message)
```

### 2.2 修复行距密集

**修改位置:** `_format_search_results` 方法中资源行的拼接逻辑

**修改内容:** 每行资源后添加空行，形成视觉分隔

```python
# 修改前 (第845行)
line = f"{ordinal} {pan_type} | {display_title} | {size} | {res_source} | {points_str}{official_str}"
lines.append(line)

# 修改后
line = f"{ordinal} {pan_type} | {display_title} | {size} | {res_source} | {points_str}{official_str}"
lines.append(line)
lines.append('')  # 添加空行分隔
```

### 2.3 修复分隔符不一致

**修改位置:** `_format_search_results` 方法中 `display_title` 的构建逻辑（第821-823行）

**修改内容:** 清理 `title` 和 `remark` 中的换行符和多余空白

```python
# 修改前
title = res.get("title") or "未知标题"
remark = res.get("remark")
display_title = f"{title} {remark}" if remark else title

# 修改后
title = (res.get("title") or "未知标题").replace("\n", " ").replace("\r", "")
remark = res.get("remark")
if remark:
    remark = remark.replace("\n", " ").replace("\r", "")
display_title = f"{title} {remark}" if remark else title
```

---

## 3. 修复后的格式示例

### 电影搜索结果
```
🔍 搜索结果 - 出走的决心
━━━━━━━━━━━━━━

① 115 | 出走的决心 (2024) 4K HQ DV 60fps DTS&DDP HiveWeb | 28.3GB | 4K WEB-DL/WEBRip | 💰1积分 官方⭐

② 115 | 出走的决心 (2024) | 21.55 | 4K WEB-DL/WEBRip | 💰4积分

③ 115 | 出走的决心 (2024) 杜比视界版 | 13.98GB | 4K WEB-DL/WEBRip | 💰4积分

④ 115 | 出走的决心 (2024) 4K SDR 60帧 高码率 DTS音轨 | 22.8G | 4K WEB-DL/WEBRip | 🆓
...
━━━━━━━━━━━━━━
💡 回复「1？」查看详情
```

### 剧集搜索结果
```
🔍 搜索结果 - 逐玉
━━━━━━━━━━━━━━

① 115 | 逐玉 (2026) S01E01-E27 1080P NF WEB-DL DDP5.1 内封简繁 HiveWeb | 51.93GB | 1080P WEB-DL/WEBRip | 🆓 官方⭐

② 115 | 逐玉 (2026) S01E01-E27 4K WEB-DL 60FPS HDR HiveWeb | 127.88GB | 4K WEB-DL/WEBRip | 🆓 官方⭐
...
⑨ 115 | 逐玉 (2026) S01.1080p.NF.WEB-DL.DDP.5.1.H.264 01-23 | 10.45GB | 1080P WEB-DL/WEBRip | 💰4积分

⑩ 115 | 逐玉 (2026) S01.2026.2160p.IQ.WEB-DL.H265.DDP5.1 [国语/内封简繁英多国软字幕/4K杜比环绕声] 01-24 | 6.30 GB | 4K WEB-DL/WEBRip | 💰4积分
━━━━━━━━━━━━━━
💡 回复「1？」查看详情
```

---

## 4. 影响范围

- **修改文件:** `plugins.v2/hdhivesearch/__init__.py`
  - `_format_search_results` - 移除重复标题、添加行距分隔、清理换行符
- **无破坏性变更:** 仅优化消息格式，不改变业务逻辑
- **调用方无需修改:** `_handle_search` 调用方式保持不变

---

## 5. 实施步骤

1. 修改 `_format_search_results` 方法签名，移除 `keyword` 参数
2. 移除标题行的生成代码
3. 每行资源后添加空行
4. 清理 title 和 remark 中的换行符
5. 验证消息格式符合预期
