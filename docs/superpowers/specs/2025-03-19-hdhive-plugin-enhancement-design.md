# HDHive 资源搜索插件增强版 - 设计文档

**日期**: 2025-03-19
**版本**: v1.0
**作者**: Claude Code
**状态**: 设计阶段

## 1. 概述

### 1.1 项目背景

当前 HDHive 资源搜索插件（v1.0.0）是初版，以 Nullbr 资源搜索插件为模板开发。本设计旨在增强插件功能，新增 CMS 自动转存、统计系统、代理重试机制、微信格式化、资源优先级配置和 Premium 用户控制等功能。

### 1.2 设计目标

- 保留所有现有功能（用户信息查询、每日签到、免费额度查询、资源搜索、详情查看、积分解锁）
- 新增 CMS 自动转存功能（115 网盘资源解锁后自动转存到 CloudSyncMedia）
- 实现统计系统（搜索次数、转存次数、成功率）
- 完善代理重试机制（系统代理→直连→错误分类处理）
- 支持微信企业应用消息格式化
- 支持网盘资源优先级配置
- 添加 Premium 用户权限控制

## 2. 架构设计

### 2.1 目录结构

```
hdhivesearch/
├── __init__.py           # 插件主类（约1000行）
├── hdhive_api.py         # HDHive API 客户端（增强重试逻辑）
├── cms_client.py         # CloudSyncMedia 客户端（新增，约150行）
└── requirements.txt      # 依赖保持不变
```

### 2.2 代码组织原则

- **适度拆分**：只将 CMS 客户端独立为 `cms_client.py`，其他逻辑保持在 `__init__.py`
- **模块化设计**：每个功能模块职责单一，接口清晰
- **复用现有代码**：直接复用 Nullbr 插件的 CMS 客户端和微信格式化逻辑

## 3. 核心功能设计

### 3.0 资源搜索功能设计

#### 3.0.1 搜索工作流程

**完整搜索流程：**

```python
def _handle_search(self, channel, userid, keyword: str):
    """
    处理用户搜索请求
    流程：影片名 → TMDB识别 → HDHive API搜索 → 按优先级排序 → 返回结果
    """
    if not keyword:
        self._show_help(channel, userid)
        return

    try:
        # 1. 更新搜索统计
        self._stats['total_searches'] += 1

        # 2. 通过 MoviePilot 媒体识别链获取 TMDB 信息
        tmdb_id, media_type = self._search_tmdb(keyword)
        if not tmdb_id:
            self._stats['failed_searches'] += 1
            self._send_message(channel, userid, "搜索失败",
                f"未找到影片「{keyword}」的TMDB信息，请确认影片名称是否正确。")
            return

        # 3. 调用 HDHive API 获取资源列表
        resources = self._api.get_resources(media_type, tmdb_id)
        if not resources:
            self._stats['failed_searches'] += 1
            self._send_message(channel, userid, "搜索结果",
                f"影片「{keyword}」暂无可用资源。")
            return

        # 4. 按网盘优先级排序
        sorted_resources = self._sort_resources_by_priority(resources)

        # 5. 缓存搜索结果（5分钟有效期）
        cache_key = f"{userid}_{int(time.time() // 300)}"
        self._search_history[cache_key] = {
            "keyword": keyword,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "resources": sorted_resources,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(sorted_resources)
        }

        # 6. 更新成功统计
        self._stats['successful_searches'] += 1
        self._stats['last_search_time'] = datetime.now().isoformat()

        # 7. 发送搜索结果
        message = self._format_search_results(keyword, sorted_resources)
        self._send_message(channel, userid, f"🔍 搜索结果 - {keyword}", message)

    except HDHiveException as e:
        logger.error(f"HDHive搜索失败: {e}")
        self._stats['failed_searches'] += 1
        self._handle_api_error(e, channel, userid)
    except Exception as e:
        logger.error(f"搜索异常: {e}")
        self._stats['failed_searches'] += 1
        self._send_message(channel, userid, "搜索失败", f"发生错误: {str(e)}")
```

#### 3.0.2 TMDB 识别流程

**通过 MoviePilot 媒体识别链获取 TMDB ID：**

```python
def _search_tmdb(self, keyword: str) -> Tuple[Optional[str], Optional[str]]:
    """
    通过影片名获取 TMDB ID 和媒体类型
    使用 MoviePilot 的媒体识别链
    """
    try:
        from app.chain.media import MediaChain
        from app.core.metainfo import MetaInfo
        from app.schemas import MediaType

        # 1. 解析影片名
        meta = MetaInfo(keyword)

        # 2. 调用 MoviePilot 媒体识别链
        mediainfo = MediaChain().recognize_by_meta(meta)

        if mediainfo:
            tmdb_id = str(mediainfo.tmdb_id)
            # 判断媒体类型：电影 或 电视剧
            media_type = "movie" if mediainfo.type == MediaType.MOVIE else "tv"
            logger.info(f"TMDB识别成功: {keyword} → TMDB:{tmdb_id} ({media_type})")
            return tmdb_id, media_type

    except Exception as e:
        logger.error(f"TMDB搜索失败: {e}")

    return None, None
```

#### 3.0.3 HDHive API 调用

**在 `hdhive_api.py` 中实现资源搜索接口：**

```python
class HDHiveAPI:
    def get_resources(self, media_type: str, tmdb_id: str) -> List[Dict]:
        """
        通过 TMDB ID 获取资源列表

        Args:
            media_type: 媒体类型 ("movie" 或 "tv")
            tmdb_id: TMDB ID

        Returns:
            资源列表，每个资源包含：
            - slug: 资源唯一标识
            - title: 资源标题
            - pan_type: 网盘类型 (115, 123, quark, baidu, ed2k, magnet)
            - share_size: 资源大小
            - video_resolution: 视频分辨率列表
            - source: 资源来源列表
            - subtitle_language: 字幕语言列表
            - subtitle_type: 字幕类型列表
            - remark: 备注
            - unlock_points: 解锁积分（null 或 0 表示免费）
            - is_official: 是否官方资源
            - is_unlocked: 当前用户是否已解锁
            - validate_status: 验证状态
            - last_validated_at: 最后验证时间
        """
        endpoint = f"/resources/{media_type}/{tmdb_id}"

        try:
            # 使用带重试的请求方法
            result = self._request_with_fallback("GET", endpoint)

            # HDHive API 返回格式: {"success": true, "data": [...]}
            if isinstance(result, dict) and "data" in result:
                resources = result.get("data", [])
            elif isinstance(result, list):
                resources = result
            else:
                resources = []

            logger.info(f"HDHive API 搜索成功: TMDB:{tmdb_id}, 找到 {len(resources)} 个资源")
            return resources

        except HDHiveException as e:
            logger.error(f"HDHive API 搜索失败: {e}")
            raise
        except Exception as e:
            logger.error(f"HDHive API 搜索异常: {e}")
            raise HDHiveException("UNKNOWN_ERROR", "搜索异常", str(e))
```

#### 3.0.4 API 响应示例

**HDHive API 响应格式：**

```json
{
  "success": true,
  "code": "200",
  "message": "success",
  "data": [
    {
      "slug": "a1b2c3d4e5f647898765432112345678",
      "title": "Fight Club 4K REMUX",
      "pan_type": "115",
      "share_size": "58.3 GB",
      "video_resolution": ["2160p"],
      "source": ["REMUX"],
      "subtitle_language": ["中文", "英文"],
      "subtitle_type": ["外挂"],
      "remark": "中英双字",
      "unlock_points": 10,
      "unlocked_users_count": 42,
      "validate_status": "valid",
      "validate_message": null,
      "last_validated_at": "2025-01-08 12:00:00",
      "is_official": true,
      "is_unlocked": false,
      "user": {
        "id": 1,
        "nickname": "HDHive",
        "avatar_url": "https://example.com/avatar.jpg"
      },
      "created_at": "2025-01-01 10:00:00"
    }
  ],
  "meta": {
    "total": 1
  }
}
```

#### 3.0.5 搜索结果格式化

```python
def _format_search_results(self, keyword: str, resources: List[Dict]) -> str:
    """格式化搜索结果为用户友好的消息"""
    lines = [f"找到 {len(resources)} 个资源:\n"]

    for i, res in enumerate(resources[:10], 1):  # 最多显示10个
        title = res.get("title") or "未知标题"
        size = res.get("share_size") or "未知大小"
        resolution = ", ".join(res.get("video_resolution", []))
        source = ", ".join(res.get("source", []))
        subtitle = ", ".join(res.get("subtitle_language", []))
        points = res.get("unlock_points")
        is_free = points is None or points == 0
        is_official = res.get("is_official", False)

        status = "🆓" if is_free else f"💰{points}积分"
        official = "⭐官方" if is_official else ""

        line = f"{i}. {title}\n   大小: {size} | 分辨率: {resolution}\n   来源: {source} | 字幕: {subtitle}\n   {status} {official}\n"
        lines.append(line)

    lines.append("\n💡 回复数字查看详情，如「1？」")
    lines.append("💡 指定网盘类型，如「1.115？」")
    return "\n".join(lines)
```

#### 3.0.6 用户交互流程

**完整用户交互示例：**

```
用户: 权力的游戏？

插件: [调用 MediaChain 识别 TMDB]
      TMDB ID: 1399, 类型: tv

      [调用 HDHive API 搜索]
      GET /api/open/resources/tv/1399

      [按优先级排序资源]
      [发送结果]

🔍 搜索结果 - 权力的游戏
找到 15 个资源:

1. 权力的游戏 S01-S08 Complete BluRay REMUX
   大小: 285.6 GB | 分辨率: 1080p
   来源: REMUX | 字幕: 中文, 英文
   💰20积分 ⭐官方

2. 权力的游戏 S01-S08 4K WEB-DL
   大小: 156.2 GB | 分辨率: 2160p
   来源: WEB-DL | 字幕: 中英双字
   💰15积分

...

💡 回复数字查看详情，如「1？」
💡 指定网盘类型，如「1.115？」

用户: 1？

插件: [获取资源详情]
      [如果是 115 且启用 CMS，自动转存]
      [发送详情和转存结果]
```

### 3.1 CMS 自动转存功能

#### 3.1.1 工作流程

```python
def _handle_selection(self, channel, userid, index: int, pan_type: Optional[str] = None):
    # 1. 获取资源详情
    detail = self._api.get_share_detail(slug)

    # 2. 检查是否为 115 网盘且启用了 CMS
    if detail.get("pan_type") == "115" and self._cms_client:
        try:
            # 3. 解锁获取实际链接
            unlock_result = self._api.unlock_resource(slug)
            full_url = unlock_result.get("full_url")

            # 4. 自动调用 CMS 转存
            cms_result = self._cms_client.add_share_down(full_url)

            # 5. 更新统计
            self._stats['cms_transfers'] += 1
            if cms_result.get('code') == 200:
                self._stats['successful_transfers'] += 1
                self._notify_transfer_success(channel, userid, cms_result.get('message'))
            else:
                self._stats['failed_transfers'] += 1
                self._handle_cms_error(Exception(cms_result.get('message')), channel, userid)

        except Exception as e:
            self._stats['failed_transfers'] += 1
            self._handle_cms_error(e, channel, userid)
```

#### 3.1.2 CMS 客户端设计

**文件**: `cms_client.py`

**功能**:
- CMS 登录认证（Bearer Token）
- Token 自动刷新（过期前1小时更新）
- 转存接口调用
- 内网访问支持（禁用代理）

**关键方法**:
```python
class CloudSyncMediaClient:
    def __init__(self, base_url: str, username: str, password: str)
    def add_share_down(self, url: str) -> dict
    def _login(self) -> dict
    def _ensure_valid_token(self)
```

#### 3.1.3 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| cms_enabled | bool | false | 启用 CMS 转存 |
| cms_url | string | "" | CMS 服务地址 |
| cms_username | string | "" | CMS 用户名 |
| cms_password | string | "" | CMS 密码 |
| cms_timeout | int | 30 | 转存超时时间（秒） |

### 3.2 统计系统设计

#### 3.2.1 统计数据结构

```python
self._stats = {
    # 搜索统计
    'total_searches': 0,           # 总搜索次数
    'successful_searches': 0,      # 成功搜索次数
    'failed_searches': 0,          # 失败搜索次数

    # 转存统计
    'cms_transfers': 0,            # CMS转存次数
    'successful_transfers': 0,     # 成功转存次数
    'failed_transfers': 0,         # 失败转存次数

    # 计算字段
    'transfer_success_rate': 0.0,  # 转存成功率（百分比）

    # 时间记录
    'last_search_time': None,      # 最后搜索时间（ISO 8601）
    'last_transfer_time': None,    # 最后转存时间（ISO 8601）
}
```

#### 3.2.2 统计更新时机

- 搜索成功/失败时更新搜索计数和最后搜索时间
- CMS 转存成功/失败时更新转存计数、成功率和最后转存时间
- 统计数据持久化到插件配置（通过 `update_config()`）

#### 3.2.3 统计查询接口

**新增命令**: `/hdhive_stats`

**显示格式**:
```
📊 HDHive 插件统计

🔍 搜索统计
   总搜索次数: 156
   成功: 148 (94.9%)
   失败: 8

📦 转存统计
   转存次数: 45
   成功: 42 (93.3%)
   失败: 3

⏰ 最后活动
   搜索: 2025-03-19 18:30
   转存: 2025-03-19 17:45
```

### 3.3 代理重试机制设计

#### 3.3.1 重试策略

**文件**: `hdhive_api.py`

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class HDHiveAPI:
    def __init__(self, api_key: str, base_url: str = None, timeout: int = 30):
        # 配置重试策略
        retry_strategy = Retry(
            total=3,                           # 最多重试3次
            status_forcelist=[429, 500, 502, 503, 504, 408],
            backoff_factor=1,                  # 指数退避因子
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = requests.Session()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
```

#### 3.3.2 双重访问机制

```python
def _request_with_fallback(self, method: str, endpoint: str, **kwargs):
    url = urljoin(self.base_url, endpoint)

    # 1. 首先尝试使用系统代理
    try:
        response = self.session.request(method, url, timeout=(10, 30), **kwargs)
        logger.info(f"使用系统代理请求成功，状态码: {response.status_code}")
        return self._process_response(response)

    except (Timeout, ConnectionError) as e:
        logger.warning(f"系统代理访问失败: {e}，尝试直连")

        # 2. 创建禁用代理的临时 session
        direct_session = requests.Session()
        direct_session.headers.update(self.session.headers)
        direct_session.proxies = {'http': None, 'https': None}

        # 3. 直连重试
        response = direct_session.request(method, url, timeout=(10, 30), **kwargs)
        logger.info(f"直连请求成功，状态码: {response.status_code}")
        return self._process_response(response)
```

#### 3.3.3 HTTP 错误分类处理

```python
ERROR_CODES = {
    "MISSING_API_KEY": (401, "缺少API Key", "请在插件配置中设置"),
    "INVALID_API_KEY": (401, "无效的API Key", "请检查API Key是否正确"),
    "DISABLED_API_KEY": (401, "API Key已被禁用", "请联系HDHive客服"),
    "EXPIRED_API_KEY": (401, "API Key已过期", "请更新API Key"),
    "VIP_REQUIRED": (403, "需要VIP会员", "此功能需要Premium会员"),
    "RATE_LIMIT_EXCEEDED": (429, "请求过于频繁", "请等待几秒后重试"),
    "INSUFFICIENT_POINTS": (402, "积分不足", "解锁资源需要足够积分"),
}

# 处理 429 错误，读取 Retry-After 头
if response.status_code == 429:
    retry_after = response.headers.get("Retry-After", "5")
    raise HDHiveException("RATE_LIMIT_EXCEEDED",
        "请求过于频繁",
        f"请等待 {retry_after} 秒后重试")
```

### 3.4 微信格式化设计

#### 3.4.1 格式化逻辑

**直接复刻 Nullbr 插件的 `_format_message_for_wechat` 方法**:

```python
def _format_message_for_wechat(self, text: str) -> str:
    """格式化消息以兼容微信企业应用显示"""
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        stripped_line = line.strip()

        # 标题行（emoji + 中文冒号）
        if ('🎬' in stripped_line or '🎯' in stripped_line or
            '✅' in stripped_line or '❌' in stripped_line) and '：' in stripped_line:
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
            formatted_lines.append(stripped_line)
            formatted_lines.append('')

        # 编号列表项
        elif re.match(r'^\d+\.', stripped_line):
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
            formatted_lines.append(stripped_line)

        # 分隔符和提示
        elif stripped_line.startswith('---') or stripped_line.startswith('💡'):
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
            formatted_lines.append(stripped_line)

        else:
            formatted_lines.append(stripped_line)

    return '\n'.join(formatted_lines)
```

#### 3.4.2 消息发送拦截

```python
def post_message(self, channel, title: str, text: str, userid: str = None):
    """发送消息，自动处理微信格式兼容"""
    # 检测是否为微信通知渠道
    if self._is_wechat_channel(channel):
        formatted_text = self._format_message_for_wechat(text)
    else:
        formatted_text = text

    super().post_message(channel=channel, title=title, text=formatted_text, userid=userid)

def _is_wechat_channel(self, channel) -> bool:
    """检测是否为微信通知渠道"""
    try:
        if hasattr(channel, 'name'):
            channel_name = str(channel.name).lower()
        elif hasattr(channel, 'type'):
            channel_name = str(channel.type).lower()
        else:
            channel_name = str(channel).lower()

        return 'wechat' in channel_name or 'wecom' in channel_name or 'wework' in channel_name
    except Exception:
        return False
```

### 3.5 资源优先级配置设计

#### 3.5.1 配置项

| 配置项 | 类型 | 默认值 | 可选值 |
|--------|------|--------|--------|
| priority_1 | string | "115" | 115, 123, quark, baidu |
| priority_2 | string | "quark" | 115, 123, quark, baidu |
| priority_3 | string | "123" | 115, 123, quark, baidu |
| priority_4 | string | "baidu" | 115, 123, quark, baidu |

#### 3.5.2 排序逻辑

```python
def _sort_resources_by_priority(self, resources: List[Dict]) -> List[Dict]:
    """按网盘优先级排序资源"""
    priority_map = {
        self._priority_1: 1,
        self._priority_2: 2,
        self._priority_3: 3,
        self._priority_4: 4,
    }

    def get_priority(resource):
        pan_type = resource.get("pan_type", "").lower()
        # 提取网盘类型（如 "115" 从 "115网盘"）
        for key in priority_map:
            if key in pan_type:
                return priority_map[key]
        return 999  # 未知类型排在最后

    return sorted(resources, key=get_priority)
```

### 3.6 Premium 用户控制设计

#### 3.6.1 配置验证流程

```python
def init_plugin(self, config: dict = None):
    # ... 其他初始化代码 ...

    # Premium 用户配置
    self._is_premium_user = config.get("is_premium_user", False)

    # 验证 Premium 用户状态
    if self._enabled and self._is_premium_user and self._api:
        try:
            user_info = self._api.get_user_info()
            actual_vip_status = user_info.get("is_vip", False)

            if not actual_vip_status:
                logger.warning("配置为Premium用户但API Key未绑定VIP账号，已禁用Premium功能")
                self._is_premium_user = False
                self._send_warning_message("Premium功能已禁用",
                    "您的API Key未绑定VIP会员账号，Premium专属功能将不可用")
        except Exception as e:
            logger.error(f"验证Premium用户状态失败: {e}")
```

#### 3.6.2 功能访问控制

```python
def _check_premium_access(self, feature_name: str) -> bool:
    """检查是否有权限访问Premium功能"""
    if not self._is_premium_user:
        logger.warning(f"尝试访问Premium功能 {feature_name} 被拒绝")
        return False
    return True

# 在 Premium 功能前检查
def _handle_user_info(self, channel, userid):
    if not self._check_premium_access("用户信息查询"):
        self._send_message(channel, userid, "权限不足",
            "此功能需要Premium会员，请在插件配置中启用Premium用户选项")
        return
    # ... 原有逻辑 ...
```

#### 3.6.3 Premium 功能清单

| 功能 | 需要 Premium | 说明 |
|------|-------------|------|
| /hdhive_me | ✓ | 用户信息查询 |
| /hdhive_checkin | ✓ | 每日签到 |
| /hdhive_quota | ✓ | 免费额度查询 |
| 资源搜索 | ✗ | 免费接口 |
| 资源解锁 | ✗ | 免费接口 |
| CMS 转存 | ✗ | 不依赖 Premium |

## 4. 错误处理设计

### 4.1 统一错误处理

```python
class HDHiveSearch(_PluginBase):
    # 错误统计
    _error_counts = {
        'api_timeout': 0,
        'api_auth_failed': 0,
        'cms_timeout': 0,
        'cms_auth_failed': 0,
        'insufficient_points': 0,
        'rate_limit_exceeded': 0,
    }

    def _handle_api_error(self, error: HDHiveException, channel, userid):
        """统一处理 HDHive API 错误"""
        error_code = error.code

        # 更新错误统计
        if error_code not in self._error_counts:
            self._error_counts[error_code] = 0
        self._error_counts[error_code] += 1

        # 根据错误类型返回用户友好的消息
        error_messages = {
            "MISSING_API_KEY": "❌ API Key 未配置",
            "INVALID_API_KEY": "❌ API Key 无效，请检查配置",
            "DISABLED_API_KEY": "❌ API Key 已被禁用",
            "EXPIRED_API_KEY": "❌ API Key 已过期",
            "VIP_REQUIRED": "❌ 此功能需要 Premium 会员",
            "RATE_LIMIT_EXCEEDED": f"⏳ 请求过于频繁，{error.description}",
            "INSUFFICIENT_POINTS": "💰 积分不足，无法解锁此资源",
            "TIMEOUT": "⏱️ 请求超时，请稍后重试",
            "CONNECTION_ERROR": "🌐 网络连接失败，请检查网络",
        }

        message = error_messages.get(error_code, f"❌ 未知错误: {error.message}")
        self._send_message(channel, userid, "操作失败", message)

        # 记录日志
        logger.error(f"HDHive API 错误: [{error_code}] {error.message} - {error.description}")
```

### 4.2 CMS 错误处理

```python
def _handle_cms_error(self, error: Exception, channel, userid):
    """统一处理 CMS 错误"""
    error_type = type(error).__name__

    if error_type == "ConnectionError":
        message = "❌ CMS 服务器连接失败，请检查 CMS 地址和网络"
        self._error_counts['cms_timeout'] += 1
    elif error_type == "HTTPError" and error.response.status_code == 401:
        message = "❌ CMS 认证失败，请检查用户名和密码"
        self._error_counts['cms_auth_failed'] += 1
    elif "登录失败" in str(error):
        message = "❌ CMS 登录失败，请检查用户名和密码"
        self._error_counts['cms_auth_failed'] += 1
    else:
        message = f"❌ CMS 转存失败: {str(error)}"
        self._error_counts['cms_timeout'] += 1

    self._send_message(channel, userid, "转存失败", message)
    logger.error(f"CMS 错误: {error_type} - {str(error)}")
```

### 4.3 用户通知模板

```python
# 搜索成功
def _notify_search_success(self, channel, userid, keyword: str, count: int):
    message = f"""
🔍 搜索完成

影片: {keyword}
找到: {count} 个资源

💡 回复数字查看详情
"""
    self._send_message(channel, userid, "搜索成功", message.strip())

# 解锁成功
def _notify_unlock_success(self, channel, userid, title: str, points_used: int):
    if points_used > 0:
        message = f"""
✅ 解锁成功

影片: {title}
消耗积分: {points_used}

📦 正在转存到 CMS...
"""
    else:
        message = f"""
✅ 解锁成功（免费资源）

影片: {title}

📦 正在转存到 CMS...
"""
    self._send_message(channel, userid, "解锁成功", message.strip())

# 转存成功
def _notify_transfer_success(self, channel, userid, cms_message: str):
    message = f"""
📦 CMS 转存成功

{cms_message}

✅ 资源已添加到您的 CMS 下载队列
"""
    self._send_message(channel, userid, "转存成功", message.strip())
```

## 5. 配置界面设计

### 5.1 完整配置表单

```python
def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
    return [
        {
            "component": "VForm",
            "content": [
                # 基础配置
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 6},
                            "content": [
                                {
                                    "component": "VSwitch",
                                    "props": {
                                        "model": "enabled",
                                        "label": "启用插件"
                                    }
                                }
                            ]
                        },
                        {
                            "component": "VCol",
                            "props": {"cols": 12, "md": 6},
                            "content": [
                                {
                                    "component": "VSwitch",
                                    "props": {
                                        "model": "is_premium_user",
                                        "label": "Premium用户"
                                    }
                                }
                            ]
                        }
                    ]
                },
                # API 配置
                {
                    "component": "VTextField",
                    "props": {
                        "model": "api_key",
                        "label": "API Key",
                        "type": "password"
                    }
                },
                {
                    "component": "VTextField",
                    "props": {
                        "model": "api_base_url",
                        "label": "API地址"
                    }
                },
                # 网盘优先级
                {
                    "component": "VDiv"
                },
                {
                    "component": "VCard",
                    "props": {"title": "网盘优先级"},
                    "content": [
                        {
                            "component": "VSelect",
                            "props": {
                                "model": "priority_1",
                                "label": "第一优先级",
                                "items": ["115", "123", "quark", "baidu"]
                            }
                        },
                        {
                            "component": "VSelect",
                            "props": {
                                "model": "priority_2",
                                "label": "第二优先级",
                                "items": ["115", "123", "quark", "baidu"]
                            }
                        },
                        {
                            "component": "VSelect",
                            "props": {
                                "model": "priority_3",
                                "label": "第三优先级",
                                "items": ["115", "123", "quark", "baidu"]
                            }
                        },
                        {
                            "component": "VSelect",
                            "props": {
                                "model": "priority_4",
                                "label": "第四优先级",
                                "items": ["115", "123", "quark", "baidu"]
                            }
                        }
                    ]
                },
                # CMS 配置
                {
                    "component": "VDiv"
                },
                {
                    "component": "VCard",
                    "props": {"title": "CMS转存配置"},
                    "content": [
                        {
                            "component": "VSwitch",
                            "props": {
                                "model": "cms_enabled",
                                "label": "启用CMS转存"
                            }
                        },
                        {
                            "component": "VTextField",
                            "props": {
                                "model": "cms_url",
                                "label": "CMS地址"
                            }
                        },
                        {
                            "component": "VTextField",
                            "props": {
                                "model": "cms_username",
                                "label": "CMS用户名"
                            }
                        },
                        {
                            "component": "VTextField",
                            "props": {
                                "model": "cms_password",
                                "label": "CMS密码",
                                "type": "password"
                            }
                        }
                    ]
                }
            ]
        }
    ], {
        "enabled": self._enabled,
        "is_premium_user": self._is_premium_user,
        "api_key": self._api_key,
        "api_base_url": self._api_base_url,
        "priority_1": self._priority_1,
        "priority_2": self._priority_2,
        "priority_3": self._priority_3,
        "priority_4": self._priority_4,
        "cms_enabled": self._cms_enabled,
        "cms_url": self._cms_url,
        "cms_username": self._cms_username,
        "cms_password": self._cms_password
    }
```

## 6. 数据持久化设计

### 6.1 持久化数据

```python
def __update_config(self):
    """更新配置到数据库"""
    self.update_config({
        # 基础配置
        "enabled": self._enabled,
        "is_premium_user": self._is_premium_user,
        "api_key": self._api_key,
        "api_base_url": self._api_base_url,

        # 优先级配置
        "priority_1": self._priority_1,
        "priority_2": self._priority_2,
        "priority_3": self._priority_3,
        "priority_4": self._priority_4,

        # CMS 配置
        "cms_enabled": self._cms_enabled,
        "cms_url": self._cms_url,
        "cms_username": self._cms_username,
        "cms_password": self._cms_password,

        # 统计数据
        "stats": self._stats,

        # 搜索历史（保留现有）
        "search_history": self._search_history,
        "user_cache": self._user_cache
    })
```

### 6.2 数据加载

```python
def init_plugin(self, config: dict = None):
    # ... 加载配置 ...

    # 加载统计数据
    self._stats = config.get("stats", {
        'total_searches': 0,
        'successful_searches': 0,
        'failed_searches': 0,
        'cms_transfers': 0,
        'successful_transfers': 0,
        'failed_transfers': 0,
        'transfer_success_rate': 0.0,
        'last_search_time': None,
        'last_transfer_time': None,
    })
```

## 7. 版本和兼容性

### 7.1 版本信息

- **当前版本**: v1.0.0
- **目标版本**: v2.0.0
- **升级说明**: 重大版本升级，需要重新配置插件

### 7.2 兼容性

- **MoviePilot 版本**: v2.0+
- **Python 版本**: 3.10+
- **依赖库**: 保持现有依赖不变

## 8. 测试计划

### 8.1 单元测试

- CMS 客户端登录和转存功能
- HDHive API 重试机制
- 微信格式化逻辑
- 资源优先级排序

### 8.2 集成测试

- 完整工作流程：搜索→解锁→转存
- Premium 权限控制
- 错误处理和用户通知

### 8.3 手动测试

- 配置界面表单验证
- 微信企业应用消息显示
- 统计数据持久化

## 9. 实施计划

### 9.1 开发阶段

1. **阶段1**: 创建 `cms_client.py`，复用 Nullbr 的 CMS 客户端
2. **阶段2**: 增强 `hdhive_api.py`，添加重试机制
3. **阶段3**: 在 `__init__.py` 中集成 CMS 转存功能
4. **阶段4**: 实现统计系统
5. **阶段5**: 添加微信格式化和资源优先级
6. **阶段6**: 实现 Premium 用户控制
7. **阶段7**: 完善错误处理和用户通知
8. **阶段8**: 更新配置界面和文档

### 9.2 测试阶段

1. 单元测试
2. 集成测试
3. 手动测试
4. Bug 修复

### 9.3 发布阶段

1. 更新 `package.v2.json`
2. 更新 README.md
3. Git 提交和打标签
4. 通知用户升级

## 10. 风险和限制

### 10.1 风险

- CMS 转存可能失败（网络、认证、容量问题）
- HDHive API 频率限制可能影响用户体验
- Premium 用户验证可能失败（网络延迟）

### 10.2 限制

- CMS 转存仅支持 115 网盘资源
- 微信格式化仅适用于微信企业应用
- Premium 功能需要有效的 VIP 会员账号

## 11. 未来改进

### 11.1 可能的增强

- 支持更多网盘类型的自动转存
- 添加转存历史记录查询
- 支持批量转存
- 添加转存进度通知

### 11.2 性能优化

- 缓存用户 VIP 状态（减少 API 调用）
- 异步转存（不阻塞用户交互）
- 统计数据定时批量更新

## 12. 附录

### 12.1 参考资料

- [HDHive Open API 文档](../HDHive Open API 文档.txt)
- [Nullbr 资源搜索插件](../plugins.v2/nullbr_search/)
- [MoviePilot V2 插件开发文档](../../MoviePilot-Plugins/docs/V2_Plugin_Development.md)

### 12.2 变更历史

| 日期 | 版本 | 变更说明 | 作者 |
|------|------|----------|------|
| 2025-03-19 | v1.0 | 初始设计文档 | Claude Code |
