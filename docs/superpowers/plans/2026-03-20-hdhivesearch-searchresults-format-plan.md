# 搜索结果格式优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复搜索结果消息格式：移除重复标题、添加行距分隔、清理换行符

**Architecture:** 修改 `plugins.v2/hdhivesearch/__init__.py` 中的 `_format_search_results` 方法，优化消息格式化逻辑

**Tech Stack:** Python (MoviePilot 插件)

---

## 文件结构

- **修改:** `plugins.v2/hdhivesearch/__init__.py`
  - `_format_search_results` 方法 (第810-850行) - 移除重复标题、添加行距分隔、清理换行符
  - `_handle_search` 方法调用处 (第731行) - 适配方法签名变更

---

## 实施步骤

### Task 1: 修改 `_format_search_results` 方法签名和标题行

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py:810-811`

- [ ] **Step 1: 修改方法签名，移除 keyword 参数**

```python
# 修改前 (第810行)
def _format_search_results(self, keyword: str, resources: List[Dict]) -> str:

# 修改后
def _format_search_results(self, resources: List[Dict]) -> str:
```

- [ ] **Step 2: 移除重复标题行**

```python
# 修改前 (第811行)
lines = [f"🔍 搜索结果 - {keyword}", "━━━━━━━━━━━━━━"]

# 修改后
lines = ["━━━━━━━━━━━━━━"]
```

- [ ] **Step 3: 提交变更**

```bash
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "fix: 移除 _format_search_results 中重复的标题行"
```

---

### Task 2: 添加行距分隔

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py:845-846`

- [ ] **Step 1: 在每行资源后添加空行分隔**

```python
# 修改前 (第845-846行)
line = f"{ordinal} {pan_type} | {display_title} | {size} | {res_source} | {points_str}{official_str}"
lines.append(line)

# 修改后
line = f"{ordinal} {pan_type} | {display_title} | {size} | {res_source} | {points_str}{official_str}"
lines.append(line)
lines.append('')  # 添加空行分隔
```

- [ ] **Step 2: 提交变更**

```bash
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "fix: 添加资源列表行距分隔"
```

---

### Task 3: 清理 title 和 remark 中的换行符

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py:820-823`

- [ ] **Step 1: 清理 title 和 remark 中的换行符**

```python
# 修改前 (第820-823行)
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

- [ ] **Step 2: 提交变更**

```bash
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "fix: 清理 title 和 remark 中的换行符"
```

---

### Task 4: 更新调用方方法签名

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py:731`

- [ ] **Step 1: 更新 _handle_search 中对 _format_search_results 的调用**

```python
# 修改前 (第731行)
message = self._format_search_results(keyword, sorted_resources)

# 修改后
message = self._format_search_results(sorted_resources)
```

- [ ] **Step 2: 提交变更**

```bash
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "fix: 更新 _handle_search 调用适配新方法签名"
```

---

### Task 5: 整体验证

- [ ] **Step 1: 运行语法检查**

```bash
python -m py_compile plugins.v2/hdhivesearch/__init__.py
```

- [ ] **Step 2: 确认所有修改已提交**

```bash
git log --oneline -5
```

---

## 预期修改总结

| 文件 | 修改内容 |
|------|----------|
| `__init__.py:810` | 方法签名移除 `keyword` 参数 |
| `__init__.py:811` | 移除重复标题行 `f"🔍 搜索结果 - {keyword}"` |
| `__init__.py:820-823` | 清理 title 和 remark 中的换行符 |
| `__init__.py:846` | 每行资源后添加空行分隔 |
| `__init__.py:731` | 调用方适配新方法签名 |
