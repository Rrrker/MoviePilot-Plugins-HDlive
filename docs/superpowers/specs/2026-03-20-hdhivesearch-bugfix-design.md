# HDHiveSearch 插件修复设计文档

**日期:** 2026-03-20
**问题:** API地址拼接错误 + 搜索结果微信消息格式优化

---

## 1. 问题概述

### 问题1: API地址拼接错误
- **现象:** 用户在配置栏填入 `https://hdhive.com/api/open` 时，API调用失败
- **原因:** `urljoin` 拼接URL时，如果 base_url 不以 `/` 结尾，会错误地替换路径段
  - `urljoin("https://hdhive.com/api/open", "resources/movie/550")` → `https://hdhive.com/api/resources/movie/550` (错误)
  - 正确应为: `https://hdhive.com/api/open/resources/movie/550`
- **触发条件:** 用户配置的 `api_base_url` 不以 `/` 结尾

### 问题2: 搜索结果微信消息格式不够清晰
- **现象:** 微信中显示的信息排列不够紧凑清晰
- **需求:** 加入 remark 字段，优化显示结构

---

## 2. 修复方案

### 2.1 API地址拼接修复

**修改文件:** `plugins.v2/hdhivesearch/hdhive_api.py`

**修改位置:** `HDHiveAPI.__init__` 方法

**修改内容:**
```python
def __init__(self, api_key: str, base_url: str = None, timeout: int = 30, use_proxy: bool = True, proxy_url: str = None):
    self.api_key = api_key
    # 确保 base_url 以 / 结尾，保证 urljoin 正确拼接
    self.base_url = base_url
    if self.base_url and not self.base_url.endswith('/'):
        self.base_url = self.base_url + '/'
```

**逻辑说明:**
- 仅当用户输入的 base_url 不为空且不以 `/` 结尾时，才追加 `/`
- 保持向后兼容，不影响空值和已有尾部斜杠的情况

---

### 2.2 搜索结果格式化优化

**修改文件:** `plugins.v2/hdhivesearch/__init__.py`

**修改位置:** `_format_search_results` 方法

**格式规范:**

| 字段 | 来源 | 说明 |
|------|------|------|
| 序号 | 枚举 | ①②③... 序号 |
| 网盘 | `pan_type` | 115/123/quark/baidu |
| 标题 | `title` + `remark` | 如有 remark 则拼接在标题后 |
| 大小 | `share_size` | 显示原始格式 |
| 分辨率+来源 | `video_resolution` + `source` | 合并显示，如"4K REMUX"、"1080P WEB-DL" |
| 积分状态 | `unlock_points` | 🆓 免费 或 💰N积分 |
| 官方标记 | `is_official` | 仅当 true 时显示"官方⭐" |

**显示格式:**
```
🔍 搜索结果 - {影片名}
━━━━━━━━━━━━━━
① 115 | 影片名 杜比视界 | 58.3GB | 4K REMUX | 🆓
② 115 | 影片名 | 2.3GB | 1080P WEB-DL | 💰10积分 | 官方⭐
① 115 | S1E01-E05合集 | 5集 | 2.1GB | 1080P | 🆓
② 115 | S1E06 | 450MB | 1080P | 💰10积分 | 杜比视界
━━━━━━━━━━━━━━
💡 回复「1？」查看详情
```

**字段拼接规则:**
1. `title` + `remark`: 用空格分隔，如 `影片名 杜比视界`
2. `video_resolution` + `source`: 用空格分隔，如 `4K REMUX`
3. `subtitle_language` 和 `subtitle_type` **不显示**在搜索列表中，仅在详情页展示
4. 当 `is_official: true` 时，在末尾添加"官方⭐"

---

## 3. 实施步骤

1. **修复API地址拼接**
   - 在 `HDHiveAPI.__init__` 中添加 base_url 尾部斜杠检查

2. **优化搜索结果格式化**
   - 修改 `_format_search_results` 方法
   - 加入 remark 字段显示
   - 优化字段拼接逻辑

3. **测试验证**
   - 测试带尾部斜杠的URL
   - 测试不带尾部斜杠的URL
   - 测试微信消息显示效果

---

## 4. 影响范围

- **API模块:** `hdhive_api.py` - base_url 处理逻辑
- **插件主模块:** `__init__.py` - _format_search_results 方法
- **无破坏性变更:** 仅优化显示，不改变API调用逻辑
