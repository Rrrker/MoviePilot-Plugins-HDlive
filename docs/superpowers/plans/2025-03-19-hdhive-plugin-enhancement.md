# HDHive 资源搜索插件增强版 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强 HDHive 资源搜索插件，新增 CMS 自动转存、统计系统、代理重试、微信格式化、资源优先级配置和 Premium 用户控制功能

**Architecture:** 基于 MoviePilot V2 插件系统，通过事件驱动架构处理用户消息，集成 HDHive Open API 进行资源搜索，使用 CloudSyncMedia 客户端进行自动转存，采用双重访问机制（系统代理→直连）处理网络请求

**Tech Stack:** Python 3.10+, MoviePilot V2 Plugin SDK, requests/urllib3, MoviePilot MediaChain, Vuetify (UI)

---

## 文件结构

```
MoviePilot-Plugins/plugins.v2/hdhivesearch/
├── __init__.py           # 插件主类（修改，从 ~625行 → ~1000行）
├── hdhive_api.py         # HDHive API 客户端（修改，增强重试逻辑）
├── cms_client.py         # CloudSyncMedia 客户端（新建，~150行）
└── requirements.txt      # 保持不变
```

**文件职责：**
- `cms_client.py` - CloudSyncMedia API 客户端，处理登录认证和转存请求
- `hdhive_api.py` - HDHive Open API 客户端，实现双重访问机制和错误分类处理
- `__init__.py` - 插件主类，事件处理、用户交互、业务逻辑协调

---

## Task 1: 创建 CloudSyncMedia 客户端

**目标:** 实现与 CloudSyncMedia 系统的集成，支持自动转存 115 网盘资源

**Files:**
- Create: `plugins.v2/hdhivesearch/cms_client.py`
- Reference: `plugins.v2/nullbr_search/cms_client.py`（直接复用）

- [ ] **Step 1: 创建 cms_client.py 文件基础结构**

```python
# plugins.v2/hdhivesearch/cms_client.py
"""
CloudSyncMedia 客户端
用于将 115 网盘资源自动转存到 CloudSyncMedia 系统
"""

import requests
import time
from app.log import logger


class CloudSyncMediaClient:
    """CloudSyncMedia客户端"""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.token = None
        self.token_expiry = 0

        # 配置请求会话
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

        # CMS一般为内网服务，禁用代理访问
        self.session.proxies = {
            'http': None,
            'https': None
        }

        # 初始化时获取token
        self._ensure_valid_token()
```

- [ ] **Step 2: 实现登录方法**

```python
    def _login(self) -> dict:
        """登录CMS系统获取token"""
        try:
            response = self.session.post(
                f'{self.base_url}/api/auth/login',
                json={
                    'username': self.username,
                    'password': self.password
                },
                timeout=(10, 30)
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') != 200 or 'data' not in data:
                raise ValueError(f'CMS登录失败: {data}')

            return data['data']

        except requests.exceptions.RequestException as e:
            logger.error(f'CMS登录失败: {str(e)}')
            raise
```

- [ ] **Step 3: 实现 token 管理方法**

```python
    def _ensure_valid_token(self):
        """确保有效的token"""
        current_time = time.time()

        # 如果token不存在或距离过期时间不到1小时，重新获取token
        if not self.token or current_time >= (self.token_expiry - 3600):
            login_data = self._login()
            self.token = login_data['token']

            # 设置token过期时间为24小时后
            self.token_expiry = current_time + 86400

            # 更新session的Authorization header
            self.session.headers.update({
                'Authorization': f'Bearer {self.token}'
            })

            logger.info("CMS token已更新")
```

- [ ] **Step 4: 实现转存方法**

```python
    def add_share_down(self, url: str) -> dict:
        """添加分享链接到CMS系统进行转存"""
        if not url:
            raise ValueError('转存链接不能为空')

        try:
            self._ensure_valid_token()

            response = self.session.post(
                f'{self.base_url}/api/cloud/add_share_down',
                json={'url': url},
                timeout=(10, 30)
            )
            response.raise_for_status()
            result = response.json()

            logger.info(f"CMS转存请求已发送: {url}")
            return result

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # token可能过期，强制重新获取
                self.token = None
                self._ensure_valid_token()

                # 重试请求
                response = self.session.post(
                    f'{self.base_url}/api/cloud/add_share_down',
                    json={'url': url},
                    timeout=(10, 30)
                )
                response.raise_for_status()
                return response.json()
            raise
        except Exception as e:
            logger.error(f'CMS转存请求失败: {str(e)}')
            raise
```

- [ ] **Step 5: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/cms_client.py`
Expected: 无语法错误

- [ ] **Step 6: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/cms_client.py
git commit -m "feat(hdhivesearch): add CloudSyncMedia client for auto-transfer"
```

---

## Task 2: 增强 HDHive API 客户端的重试逻辑

**目标:** 实现双重访问机制（系统代理→直连）和 HTTP 错误分类处理

**Files:**
- Modify: `plugins.v2/hdhivesearch/hdhive_api.py`
- Reference: `plugins.v2/nullbr_search/nullbr_client.py`（重试逻辑参考）

- [ ] **Step 1: 添加必要的导入**

在 `hdhive_api.py` 文件顶部添加：

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urljoin
from typing import Dict, List, Optional
import json
```

在 `hdhive_api.py` 文件顶部添加：

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, List, Optional
```

- [ ] **Step 2: 修改 HDHiveAPI.__init__ 方法，添加重试策略**

在 `hdhive_api.py` 中找到 `__init__` 方法，替换为：

```python
def __init__(self, api_key: str, base_url: str = None, timeout: int = 30):
    self.api_key = api_key
    self.base_url = base_url or self.BASE_URL
    self.timeout = timeout

    # 配置请求会话
    self.session = requests.Session()
    self.session.headers.update({
        "X-API-Key": self.api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    })

    # 配置重试策略
    try:
        retry_strategy = Retry(
            total=3,                                # 最多重试3次
            status_forcelist=[429, 500, 502, 503, 504, 408],
            backoff_factor=1,                       # 指数退避因子
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    except Exception as e:
        logger.warning(f"重试策略配置失败: {str(e)}")
```

- [ ] **Step 3: 实现双重访问的请求方法**

在 `hdhive_api.py` 中，在 `HDHiveAPI` 类中添加新方法：

```python
def _request_with_fallback(self, method: str, endpoint: str, **kwargs) -> Dict:
    """
    发起HTTP请求，支持代理重试机制
    首先尝试使用系统代理，失败后直连
    """
    url = urljoin(self.base_url, endpoint)

    # 1. 首先尝试使用系统代理
    try:
        logger.debug("尝试使用系统代理访问HDHive API")
        response = self.session.request(
            method=method,
            url=url,
            timeout=self.timeout,
            **kwargs
        )
        logger.info(f"使用系统代理请求成功，状态码: {response.status_code}")
        return self._process_response(response)

    except (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout,
           requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
        logger.warning(f"系统代理访问失败: {str(e)}，尝试直连")

        # 2. 创建禁用代理的临时 session
        direct_session = requests.Session()
        direct_session.headers.update(self.session.headers)
        direct_session.proxies = {'http': None, 'https': None}

        # 3. 直连重试
        try:
            response = direct_session.request(
                method=method,
                url=url,
                timeout=self.timeout,
                **kwargs
            )
            logger.info(f"直连请求成功，状态码: {response.status_code}")
            return self._process_response(response)

        except Exception as direct_error:
            logger.error(f"直连也失败: {str(direct_error)}")
            raise direct_error
```

- [ ] **Step 4: 添加响应处理方法**

```python
def _process_response(self, response: requests.Response) -> Dict:
    """处理HTTP响应，检查状态码和JSON格式"""
    # 检查429频率限制
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "5")
        raise HDHiveException(
            "RATE_LIMIT_EXCEEDED",
            "请求过于频繁",
            f"请等待 {retry_after} 秒后重试"
        )

    # 解析JSON响应
    try:
        data = response.json()
    except json.JSONDecodeError:
        raise HDHiveException("INVALID_RESPONSE", "响应格式错误", "服务器返回了无效的JSON数据")

    # 检查业务逻辑错误
    if not data.get("success", False):
        code = data.get("code", "UNKNOWN_ERROR")
        message = data.get("message", "未知错误")
        description = data.get("description", "")

        # 使用预定义的错误描述
        if code in self.ERROR_CODES:
            description = self.ERROR_CODES.get(code, description)

        raise HDHiveException(code, message, description)

    return data.get("data", {})
```

- [ ] **Step 5: 修改现有 API 方法使用新的请求方法**

在 `hdhive_api.py` 中，修改以下方法使用 `_request_with_fallback`：

```python
def get_resources(self, media_type: str, tmdb_id: str) -> List[Dict]:
    """通过 TMDB ID 获取资源列表"""
    endpoint = f"/resources/{media_type}/{tmdb_id}"
    result = self._request_with_fallback("GET", endpoint)

    if isinstance(result, dict) and "data" in result:
        return result.get("data", [])
    return result if isinstance(result, list) else []

def unlock_resource(self, slug: str) -> Dict:
    """解锁资源"""
    return self._request_with_fallback("POST", "/resources/unlock", json={"slug": slug})

def get_share_detail(self, slug: str) -> Dict:
    """获取资源详情"""
    return self._request_with_fallback("GET", f"/shares/{slug}")

# 类似地修改其他方法...
```

- [ ] **Step 6: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/hdhive_api.py`
Expected: 无语法错误

- [ ] **Step 7: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/hdhive_api.py
git commit -m "feat(hdhivesearch): add retry logic with proxy fallback to API client"
```

---

## Task 3: 添加插件配置项和初始化逻辑

**目标:** 在插件主类中添加新的配置项和初始化逻辑

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 添加必要的导入（在文件顶部）**

在 `__init__.py` 文件顶部，现有导入后添加：

```python
from typing import Tuple, Optional, List, Dict, Any
from datetime import datetime
import re
import time
```

- [ ] **Step 2: 在 __init__ 方法中添加新的实例变量**

找到 `__init__` 方法，在现有的变量声明后添加：

```python
def __init__(self):
    super().__init__()

    # ... 现有变量 ...

    # Premium 用户配置
    self._is_premium_user = False

    # 网盘优先级配置
    self._priority_1 = "115"
    self._priority_2 = "quark"
    self._priority_3 = "123"
    self._priority_4 = "baidu"

    # CMS 配置
    self._cms_enabled = False
    self._cms_url = ""
    self._cms_username = ""
    self._cms_password = ""
    self._cms_client = None

    # 统计数据
    self._stats = {
        'total_searches': 0,
        'successful_searches': 0,
        'failed_searches': 0,
        'cms_transfers': 0,
        'successful_transfers': 0,
        'failed_transfers': 0,
        'transfer_success_rate': 0.0,
        'last_search_time': None,
        'last_transfer_time': None,
    }

    # 错误统计
    self._error_counts = {
        'api_timeout': 0,
        'api_auth_failed': 0,
        'cms_timeout': 0,
        'cms_auth_failed': 0,
        'insufficient_points': 0,
        'rate_limit_exceeded': 0,
    }
```

- [ ] **Step 2: 修改 init_plugin 方法加载新配置**

在 `init_plugin` 方法中添加：

```python
def init_plugin(self, config: dict = None):
    self.stop_service()

    if config:
        # ... 现有配置加载 ...

        # Premium 用户配置
        self._is_premium_user = config.get("is_premium_user", False)

        # 网盘优先级配置
        self._priority_1 = config.get("priority_1", "115")
        self._priority_2 = config.get("priority_2", "quark")
        self._priority_3 = config.get("priority_3", "123")
        self._priority_4 = config.get("priority_4", "baidu")

        # CMS 配置
        self._cms_enabled = config.get("cms_enabled", False)
        self._cms_url = config.get("cms_url", "")
        self._cms_username = config.get("cms_username", "")
        self._cms_password = config.get("cms_password", "")

        # 加载统计数据
        self._stats = config.get("stats", self._stats)

    # 初始化 HDHive API
    if self._enabled and self._api_key:
        self._api = HDHiveAPI(
            api_key=self._api_key,
            base_url=self._api_base_url
        )

        # 验证 Premium 用户状态
        if self._is_premium_user:
            self._verify_premium_user()

    # 初始化 CMS 客户端
    if self._cms_enabled and self._cms_url and self._cms_username and self._cms_password:
        try:
            from .cms_client import CloudSyncMediaClient
            self._cms_client = CloudSyncMediaClient(
                self._cms_url,
                self._cms_username,
                self._cms_password
            )
            logger.info("CloudSyncMedia客户端已初始化")
        except Exception as e:
            logger.error(f"CloudSyncMedia初始化失败: {str(e)}")
            self._cms_enabled = False
            self._cms_client = None
```

- [ ] **Step 3: 添加 Premium 用户验证方法**

```python
def _verify_premium_user(self):
    """验证 Premium 用户状态"""
    try:
        user_info = self._api.get_user_info()
        actual_vip_status = user_info.get("is_vip", False)

        if not actual_vip_status:
            logger.warning("配置为Premium用户但API Key未绑定VIP账号，已禁用Premium功能")
            self._is_premium_user = False
            # 这里可以发送系统通知
    except Exception as e:
        logger.error(f"验证Premium用户状态失败: {e}")
```

- [ ] **Step 4: 修改 __update_config 方法保存新配置**

```python
def __update_config(self):
    """更新配置到数据库"""
    self.update_config({
        # 基础配置
        "enabled": self._enabled,
        "api_key": self._api_key,
        "api_base_url": self._api_base_url,
        "notify": self._notify,

        # Premium 配置
        "is_premium_user": self._is_premium_user,

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

        # 搜索历史
        "search_history": self._search_history,
        "user_cache": self._user_cache
    })
```

- [ ] **Step 5: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 6: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): add configuration for CMS, priority, and stats"
```

---

## Task 4: 实现用户消息监听和解析

**目标:** 监听用户消息，识别搜索请求和资源选择

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 添加用户消息事件监听器**

```python
@eventmanager.register(EventType.UserMessage)
def handle_user_message(self, event: Event):
    """
    监听用户消息，识别搜索请求和资源选择
    """
    if not self._enabled:
        return

    event_data = event.event_data
    if not event_data:
        return

    # 获取消息内容
    text = event_data.get("text", "").strip()
    if not text:
        return

    channel = event_data.get("channel")
    userid = event_data.get("userid") or event_data.get("user")

    # 1. 检查是否为搜索请求（以？或?结尾）
    if text.endswith("?") or text.endswith("？"):
        keyword = text[:-1].strip()
        if keyword:
            logger.info(f"检测到搜索请求: {keyword}")
            self._handle_search(channel, userid, keyword)

    # 2. 检查是否为资源详情查看（纯数字）
    elif re.match(r'^(\d+)[\?您]?$', text):
        match = re.match(r'^(\d+)', text)
        index = int(match.group(1))
        self._handle_selection(channel, userid, index)

    # 3. 检查是否为指定网盘类型（数字.网盘类型）
    elif re.match(r'^(\d+)\.(115|123|quark|baidu)[\?您]?$', text):
        match = re.match(r'^(\d+)\.(115|123|quark|baidu)', text)
        index = int(match.group(1))
        pan_type = match.group(2)
        self._handle_selection(channel, userid, index, pan_type)
```

- [ ] **Step 2: 移除或修改旧的 handle_user_message 方法（如果存在）**

如果之前有简单的 `handle_user_message` 方法，删除或替换为上面的新实现。

- [ ] **Step 3: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 4: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): add user message listener with pattern matching"
```

---

## Task 5: 实现 TMDB 识别和资源搜索

**目标:** 通过 MoviePilot 媒体识别链获取 TMDB ID，然后调用 HDHive API 搜索资源

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 实现 TMDB 识别方法**

```python
def _search_tmdb(self, keyword: str) -> Tuple[Optional[str], Optional[str]]:
    """
    通过影片名获取 TMDB ID 和媒体类型
    使用 MoviePilot 的媒体识别链

    Args:
        keyword: 用户输入的影片名（如 "权力的游戏"）

    Returns:
        (tmdb_id, media_type) 或 (None, None)
        - tmdb_id: TMDB ID（字符串，如 "1399"）
        - media_type: "movie" 或 "tv"
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
            media_type = "movie" if mediainfo.type == MediaType.MOVIE else "tv"
            logger.info(f"TMDB识别成功: {keyword} → TMDB:{tmdb_id} ({media_type})")
            return tmdb_id, media_type
        else:
            logger.warning(f"TMDB识别失败: 未找到「{keyword}」的媒体信息")
            return None, None

    except Exception as e:
        logger.error(f"TMDB搜索异常: {e}")
        return None, None
```

- [ ] **Step 2: 实现资源排序方法**

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
        for key in priority_map:
            if key in pan_type:
                return priority_map[key]
        return 999  # 未知类型排在最后

    return sorted(resources, key=get_priority)
```

- [ ] **Step 3: 实现搜索处理方法**

```python
def _handle_search(self, channel, userid, keyword: str):
    """处理搜索请求"""
    if not keyword:
        self._show_help(channel, userid)
        return

    try:
        # 更新搜索统计
        self._stats['total_searches'] += 1

        # 1. 通过 MoviePilot 媒体识别链获取 TMDB 信息
        tmdb_id, media_type = self._search_tmdb(keyword)
        if not tmdb_id:
            self._stats['failed_searches'] += 1
            self._send_message(channel, userid, "搜索失败",
                f"未找到影片「{keyword}」的TMDB信息，请确认影片名称是否正确。")
            return

        # 2. 调用 HDHive API 获取资源列表
        resources = self._api.get_resources(media_type, tmdb_id)
        if not resources:
            self._stats['failed_searches'] += 1
            self._send_message(channel, userid, "搜索结果",
                f"影片「{keyword}」暂无可用资源。")
            return

        # 3. 按网盘优先级排序
        sorted_resources = self._sort_resources_by_priority(resources)

        # 4. 缓存搜索结果（5分钟有效期）
        cache_key = f"{userid}_{int(time.time() // 300)}"
        self._search_history[cache_key] = {
            "keyword": keyword,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "resources": sorted_resources,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(sorted_resources)
        }
        self.__update_config()

        # 5. 更新成功统计
        self._stats['successful_searches'] += 1
        self._stats['last_search_time'] = datetime.now().isoformat()

        # 6. 发送搜索结果
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

- [ ] **Step 4: 实现搜索结果格式化方法**

```python
def _format_search_results(self, keyword: str, resources: List[Dict]) -> str:
    """格式化搜索结果为用户友好的消息"""
    lines = [f"找到 {len(resources)} 个资源:\n"]

    for i, res in enumerate(resources[:10], 1):
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

- [ ] **Step 5: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 6: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): implement TMDB recognition and resource search"
```

---

## Task 6: 实现资源详情查看和 CMS 自动转存

**目标:** 处理用户选择的资源，查看详情，对 115 网盘资源自动转存

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 实现资源选择处理方法**

```python
def _handle_selection(self, channel, userid, index: int, pan_type: Optional[str] = None):
    """处理资源选择"""
    # 查找最近的搜索缓存
    cache_key = None
    for key in sorted(self._search_history.keys(), reverse=True):
        if key.startswith(str(userid)):
            cache_key = key
            break

    if not cache_key:
        self._send_message(channel, userid, "提示", "搜索记录已过期，请重新搜索。")
        return

    cache_data = self._search_history.get(cache_key)
    if not cache_data:
        self._send_message(channel, userid, "提示", "搜索记录不存在，请重新搜索。")
        return

    resources = cache_data.get("resources", [])
    if index < 1 or index > len(resources):
        self._send_message(channel, userid, "提示", f"无效的选择，请输入1-{len(resources)}之间的数字。")
        return

    resource = resources[index - 1]
    slug = resource.get("slug")

    try:
        # 1. 获取资源详情
        detail = self._api.get_share_detail(slug)
        if not detail:
            self._send_message(channel, userid, "错误", "获取资源详情失败。")
            return

        # 2. 如果指定了网盘类型，过滤
        if pan_type:
            if detail.get("pan_type", "").lower() != pan_type.lower():
                self._send_message(channel, userid, "提示", f"该资源不是 {pan_type} 网盘类型。")
                return

        # 3. 格式化并发送详情
        message = self._format_resource_detail(detail)
        self._send_message(channel, userid, "📋 资源详情", message)

        # 4. 如果是 115 网盘且启用了 CMS，自动转存
        if detail.get("pan_type") == "115" and self._cms_client:
            self._handle_cms_transfer(detail, channel, userid)
        elif detail.get("pan_type") == "115" and not self._cms_client:
            # 提示可以配置 CMS
            message += "\n\n💡 提示：配置 CloudSyncMedia 后可自动转存 115 资源"
            self._send_message(channel, userid, "提示", message)

    except HDHiveException as e:
        logger.error(f"获取资源详情失败: {e}")
        self._handle_api_error(e, channel, userid)
```

- [ ] **Step 2: 实现资源详情格式化方法**

```python
def _format_resource_detail(self, detail: Dict) -> str:
    """格式化资源详情"""
    title = detail.get("title") or "未知标题"
    pan_type = detail.get("pan_type") or "未知"
    size = detail.get("share_size") or "未知大小"
    resolution = ", ".join(detail.get("video_resolution", []))
    source = ", ".join(detail.get("source", []))
    subtitle_lang = ", ".join(detail.get("subtitle_language", []))
    subtitle_type = ", ".join(detail.get("subtitle_type", []))
    remark = detail.get("remark") or "无"
    points = detail.get("unlock_points")
    is_unlocked = detail.get("is_unlocked", False)
    is_free = points is None or points == 0
    is_official = detail.get("is_official", False)
    validate_status = detail.get("validate_status") or "未验证"
    last_validated = detail.get("last_validated_at") or "无"

    lines = [
        f"标题: {title}",
        f"网盘: {pan_type}",
        f"大小: {size}",
        f"分辨率: {resolution}",
        f"来源: {source}",
        f"字幕语言: {subtitle_lang}",
        f"字幕类型: {subtitle_type}",
        f"备注: {remark}",
        f"解锁积分: {'免费' if is_free else f'{points}积分'}",
        f"已解锁: {'是' if is_unlocked else '否'}",
        f"官方资源: {'是' if is_official else '否'}",
        f"验证状态: {validate_status}",
        f"最后验证: {last_validated}",
    ]

    return "\n".join(lines)
```

- [ ] **Step 3: 实现 CMS 转存处理方法**

```python
def _handle_cms_transfer(self, detail: Dict, channel, userid):
    """处理 CMS 转存"""
    slug = detail.get("slug")

    try:
        # 1. 解锁获取实际链接
        unlock_result = self._api.unlock_resource(slug)
        full_url = unlock_result.get("full_url")

        if not full_url:
            self._send_message(channel, userid, "转存失败", "无法获取资源链接")
            return

        # 2. 调用 CMS 转存
        self._stats['cms_transfers'] += 1
        cms_result = self._cms_client.add_share_down(full_url)

        # 3. 更新统计
        if cms_result.get('code') == 200:
            self._stats['successful_transfers'] += 1
            self._stats['last_transfer_time'] = datetime.now().isoformat()
            self._update_transfer_success_rate()

            # 4. 发送成功通知
            message = f"""
✅ 转存成功

{cms_result.get('message', '资源已添加到下载队列')}

📊 转存统计: 成功 {self._stats['successful_transfers']}/{self._stats['cms_transfers']}
"""
            self._send_message(channel, userid, "📦 转存成功", message.strip())
        else:
            self._stats['failed_transfers'] += 1
            self._handle_cms_error(Exception(cms_result.get('message', '转存失败')), channel, userid)

        # 5. 持久化配置
        self.__update_config()

    except Exception as e:
        self._stats['failed_transfers'] += 1
        logger.error(f"CMS转存失败: {e}")
        self._handle_cms_error(e, channel, userid)
```

- [ ] **Step 4: 实现转存成功率更新**

```python
def _update_transfer_success_rate(self):
    """更新转存成功率"""
    total = self._stats['cms_transfers']
    if total > 0:
        successful = self._stats['successful_transfers']
        self._stats['transfer_success_rate'] = round((successful / total) * 100, 2)
```

- [ ] **Step 5: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 6: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): implement resource detail view and CMS auto-transfer"
```

---

## Task 7: 实现错误处理和用户通知

**目标:** 统一的 API 和 CMS 错误处理，用户友好的错误消息

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 实现 API 错误处理方法**

```python
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

- [ ] **Step 2: 实现 CMS 错误处理方法**

```python
def _handle_cms_error(self, error: Exception, channel, userid):
    """统一处理 CMS 错误"""
    error_type = type(error).__name__

    if error_type == "ConnectionError":
        message = "❌ CMS 服务器连接失败，请检查 CMS 地址和网络"
        self._error_counts['cms_timeout'] += 1
    elif error_type == "HTTPError" and hasattr(error, 'response') and error.response.status_code == 401:
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

- [ ] **Step 3: 重写 post_message 方法支持微信格式化**

```python
def post_message(self, channel, title: str, text: str, userid: str = None):
    """发送消息，自动处理微信格式兼容"""
    # 检测是否为微信通知渠道
    if self._is_wechat_channel(channel):
        formatted_text = self._format_message_for_wechat(text)
    else:
        formatted_text = text

    # 调用父类的post_message方法
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

- [ ] **Step 4: 实现微信格式化方法**

```python
def _format_message_for_wechat(self, text: str) -> str:
    """格式化消息以兼容微信企业应用显示"""
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        stripped_line = line.strip()

        # 空行处理：连续空行只保留一个
        if not stripped_line:
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
            continue

        # 对于标题行（包含emoji和中文冒号），前后加空行
        if ('🎬' in stripped_line or '🎯' in stripped_line or
            '✅' in stripped_line or '❌' in stripped_line) and '：' in stripped_line:
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
            formatted_lines.append(stripped_line)
            formatted_lines.append('')
        # 对于编号列表项
        elif re.match(r'^\d+\.', stripped_line) or re.match(r'^【\d+】', stripped_line):
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
            formatted_lines.append(stripped_line)
        # 对于缩进的详情行
        elif stripped_line.startswith(' ') or stripped_line.startswith('   '):
            formatted_lines.append(stripped_line)
        # 对于分隔符和提示信息
        elif stripped_line.startswith('---') or stripped_line.startswith('💡') or stripped_line.startswith('📋'):
            if formatted_lines and formatted_lines[-1] != '':
                formatted_lines.append('')
            formatted_lines.append(stripped_line)
        else:
            formatted_lines.append(stripped_line)

    return '\n'.join(formatted_lines)
```

- [ ] **Step 5: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 6: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): add unified error handling and WeChat formatting"
```

---

## Task 8: 实现统计查询命令

**目标:** 添加 `/hdhive_stats` 命令查询插件统计信息

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 添加统计命令到 get_command 方法**

```python
@staticmethod
def get_command() -> List[Dict[str, Any]]:
    return [
        # ... 现有命令 ...
        {
            "cmd": "/hdhive_stats",
            "event": EventType.PluginAction,
            "desc": "HDHive插件统计",
            "category": "资源搜索",
            "data": {"action": "hdhive_stats"}
        }
    ]
```

- [ ] **Step 2: 在 handle_plugin_action 方法中添加统计处理**

```python
@eventmanager.register(EventType.PluginAction)
def handle_plugin_action(self, event: Event):
    # ... 现有代码 ...

    if action == "hdhive_search":
        self._handle_search(channel, userid, text)
    elif action == "hdhive_me":
        self._handle_user_info(channel, userid)
    elif action == "hdhive_checkin":
        self._handle_checkin(channel, userid)
    elif action == "hdhive_quota":
        self._handle_quota(channel, userid)
    elif action == "hdhive_stats":
        self._handle_stats_query(channel, userid)
```

- [ ] **Step 3: 实现统计查询方法**

```python
def _handle_stats_query(self, channel, userid):
    """处理统计查询"""
    # 计算成功率
    search_total = self._stats['total_searches']
    search_success_rate = round((self._stats['successful_searches'] / search_total * 100), 1) if search_total > 0 else 0

    transfer_total = self._stats['cms_transfers']
    transfer_success_rate = self._stats['transfer_success_rate']

    # 格式化时间
    last_search = self._stats.get('last_search_time', '未搜索')
    last_transfer = self._stats.get('last_transfer_time', '未转存')

    if last_search != '未搜索':
        try:
            dt = datetime.fromisoformat(last_search)
            last_search = dt.strftime("%Y-%m-%d %H:%M")
        except:
            pass

    if last_transfer != '未转存':
        try:
            dt = datetime.fromisoformat(last_transfer)
            last_transfer = dt.strftime("%Y-%m-%d %H:%M")
        except:
            pass

    # 构建统计消息
    message = f"""
📊 HDHive 插件统计

🔍 搜索统计
   总搜索次数: {search_total}
   成功: {self._stats['successful_searches']} ({search_success_rate}%)
   失败: {self._stats['failed_searches']}

📦 转存统计
   转存次数: {transfer_total}
   成功: {self._stats['successful_transfers']} ({transfer_success_rate}%)
   失败: {self._stats['failed_transfers']}

⏰ 最后活动
   搜索: {last_search}
   转存: {last_transfer}
"""

    self._send_message(channel, userid, "📊 插件统计", message.strip())
```

- [ ] **Step 4: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 5: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): add stats query command"
```

---

## Task 9: 实现 Premium 权限控制

**目标:** 对 Premium 专属功能进行权限检查

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 实现 Premium 权限检查方法**

```python
def _check_premium_access(self, feature_name: str) -> bool:
    """检查是否有权限访问Premium功能"""
    if not self._is_premium_user:
        logger.warning(f"尝试访问Premium功能 {feature_name} 被拒绝")
        return False
    return True
```

- [ ] **Step 2: 在 Premium 功能前添加权限检查**

修改 `_handle_user_info` 方法：

```python
def _handle_user_info(self, channel, userid):
    """处理用户信息查询（Premium功能）"""
    if not self._check_premium_access("用户信息查询"):
        self._send_message(channel, userid, "权限不足",
            "此功能需要Premium会员，请在插件配置中启用Premium用户选项")
        return

    # ... 原有逻辑 ...
```

修改 `_handle_checkin` 方法：

```python
def _handle_checkin(self, channel, userid):
    """处理每日签到（Premium功能）"""
    if not self._check_premium_access("每日签到"):
        self._send_message(channel, userid, "权限不足",
            "此功能需要Premium会员，请在插件配置中启用Premium用户选项")
        return

    # ... 原有逻辑 ...
```

修改 `_handle_quota` 方法：

```python
def _handle_quota(self, channel, userid):
    """处理免费额度查询（Premium功能）"""
    if not self._check_premium_access("免费额度查询"):
        self._send_message(channel, userid, "权限不足",
            "此功能需要Premium会员，请在插件配置中启用Premium用户选项")
        return

    # ... 原有逻辑 ...
```

- [ ] **Step 3: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 4: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): add Premium permission control"
```

---

## Task 10: 更新配置界面

**目标:** 在插件配置表单中添加新的配置项

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`

- [ ] **Step 1: 更新 get_form 方法**

找到 `get_form` 方法，替换为完整的配置表单。由于表单较长，这里分段添加：

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
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "VTextField",
                                    "props": {
                                        "model": "api_key",
                                        "label": "API Key",
                                        "type": "password",
                                        "placeholder": "输入HDHive API Key"
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    "component": "VRow",
                    "content": [
                        {
                            "component": "VCol",
                            "props": {"cols": 12},
                            "content": [
                                {
                                    "component": "VTextField",
                                    "props": {
                                        "model": "api_base_url",
                                        "label": "API地址",
                                        "placeholder": "https://hdhive.com/api/open"
                                    }
                                }
                            ]
                        }
                    ]
                },
                # 网盘优先级配置
                {
                    "component": "VDiv"
                },
                {
                    "component": "VCard",
                    "props": {"title": "网盘优先级"},
                    "content": [
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 6, "md": 3},
                                    "content": [
                                        {
                                            "component": "VSelect",
                                            "props": {
                                                "model": "priority_1",
                                                "label": "第一优先级",
                                                "items": ["115", "123", "quark", "baidu"]
                                            }
                                        }
                                    ]
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 6, "md": 3},
                                    "content": [
                                        {
                                            "component": "VSelect",
                                            "props": {
                                                "model": "priority_2",
                                                "label": "第二优先级",
                                                "items": ["115", "123", "quark", "baidu"]
                                            }
                                        }
                                    ]
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 6, "md": 3},
                                    "content": [
                                        {
                                            "component": "VSelect",
                                            "props": {
                                                "model": "priority_3",
                                                "label": "第三优先级",
                                                "items": ["115", "123", "quark", "baidu"]
                                            }
                                        }
                                    ]
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 6, "md": 3},
                                    "content": [
                                        {
                                            "component": "VSelect",
                                            "props": {
                                                "model": "priority_4",
                                                "label": "第四优先级",
                                                "items": ["115", "123", "quark", "baidu"]
                                            }
                                        }
                                    ]
                                }
                            ]
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
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [
                                        {
                                            "component": "VSwitch",
                                            "props": {
                                                "model": "cms_enabled",
                                                "label": "启用CMS转存"
                                            }
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [
                                        {
                                            "component": "VTextField",
                                            "props": {
                                                "model": "cms_url",
                                                "label": "CMS地址",
                                                "placeholder": "http://cms.example.com"
                                            }
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 6},
                                    "content": [
                                        {
                                            "component": "VTextField",
                                            "props": {
                                                "model": "cms_username",
                                                "label": "CMS用户名"
                                            }
                                        }
                                    ]
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 6},
                                    "content": [
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

- [ ] **Step 2: 验证代码语法**

Run: `python -m py_compile plugins.v2/hdhivesearch/__init__.py`
Expected: 无语法错误

- [ ] **Step 3: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py
git commit -m "feat(hdhivesearch): update configuration form with new options"
```

---

## Task 11: 更新版本号和 package.json

**目标:** 更新插件版本号和 package.v2.json 中的版本信息

**Files:**
- Modify: `plugins.v2/hdhivesearch/__init__.py`
- Modify: `package.v2.json`

- [ ] **Step 1: 更新插件版本号**

在 `__init__.py` 中找到 `plugin_version` 并更新：

```python
class HDHiveSearch(_PluginBase):
    plugin_name = "HDHive资源搜索"
    plugin_desc = "通过HDHive API搜索网盘资源，支持115/123/夸克/百度网盘等，支持积分解锁、每日签到、VIP免费额度、CMS自动转存。"
    plugin_icon = "Alist_B.png"
    plugin_version = "2.0.0"  # 从 1.0.9 更新到 2.0.0
    plugin_author = "HDHive"
    author_url = "https://hdhive.com"
```

- [ ] **Step 2: 更新 package.v2.json**

找到 `HDHiveSearch` 条目，更新版本和历史：

```json
"HDHiveSearch": {
  "name": "HDHive资源搜索",
  "description": "通过HDHive API搜索网盘资源，支持115/123/夸克/百度网盘等，支持积分解锁、每日签到、VIP免费额度、健康检查、CMS自动转存、统计系统。",
  "labels": "资源搜索,网盘",
  "version": "2.0.0",
  "icon": "Alist_B.png",
  "author": "HDHive",
  "level": 1,
  "history": {
    "v2.0.0": "重大更新：新增CMS自动转存功能（115网盘资源自动转存到CloudSyncMedia）；新增统计系统（搜索次数、转存次数、成功率）；增强代理重试机制（系统代理→直连双重访问）；支持微信企业应用消息格式化；支持网盘资源优先级配置；添加Premium用户权限控制；完善错误处理和用户通知",
    "v1.0.9": "简化配置页面结构，修复前端组件兼容性问题",
    "v1.0.8": "修复API调用错误（改用get_resources接口），添加TMDB名称搜索支持，添加请求去重机制防止重复搜索，添加ChatGPT冲突警告"
  }
}
```

- [ ] **Step 3: 提交代码**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/__init__.py package.v2.json
git commit -m "chore(hdhivesearch): bump version to 2.0.0 with new features"
```

---

## Task 12: 测试和验证

**目标:** 测试所有新功能，确保正常工作

**Files:**
- Create: `test_hdhivesearch_manual.md`（测试清单）

- [ ] **Step 1: 创建测试清单文档**

```markdown
# HDHive 插件 v2.0.0 手动测试清单

## 1. 基础功能测试

### 1.1 插件初始化
- [ ] 插件能正常启用
- [ ] API Key 配置正确
- [ ] 配置项能正常保存和加载

### 1.2 资源搜索
- [ ] 发送 "影片名？" 能正常搜索
- [ ] TMDB 识别正确
- [ ] 搜索结果按优先级排序
- [ ] 搜索结果格式正确

### 1.3 资源详情
- [ ] 回复数字能查看详情
- [ ] 详情信息完整
- [ ] 指定网盘类型正常工作

## 2. CMS 转存测试

### 2.1 自动转存
- [ ] 115 资源解锁后自动转存
- [ ] 转存成功有通知
- [ ] 转存失败有错误提示

### 2.2 CMS 配置
- [ ] CMS 配置保存正确
- [ ] CMS 客户端初始化成功
- [ ] 转存统计正确更新

## 3. 统计系统测试

### 3.1 搜索统计
- [ ] 搜索次数正确计数
- [ ] 成功/失败次数正确
- [ ] 最后搜索时间正确

### 3.2 转存统计
- [ ] 转存次数正确计数
- [ ] 成功率计算正确
- [ ] 统计查询命令正常

## 4. Premium 功能测试

### 4.1 权限控制
- [ ] 未启用 Premium 时拒绝访问
- [ ] 启用 Premium 但未绑 VIP 时禁用功能
- [ ] Premium 用户正常访问

### 4.2 Premium 功能
- [ ] 用户信息查询正常
- [ ] 每日签到正常
- [ ] 免费额度查询正常

## 5. 错误处理测试

### 5.1 API 错误
- [ ] 网络超时有友好提示
- [ ] API Key 无效有明确提示
- [ ] 积分不足有提示
- [ ] 频率限制有提示

### 5.2 CMS 错误
- [ ] CMS 连接失败有提示
- [ ] CMS 认证失败有提示
- [ ] 转存失败有提示

## 6. 微信格式化测试

### 6.1 消息格式
- [ ] 微信消息格式正确
- [ ] 换行和空行处理正确
- [ ] emoji 显示正常

## 7. 配置界面测试

### 7.1 配置表单
- [ ] 所有配置项正常显示
- [ ] 配置能正常保存
- [ ] 配置能正常加载

### 7.2 优先级配置
- [ ] 网盘优先级选择正常
- [ ] 优先级生效正确
```

- [ ] **Step 2: 执行手动测试**

按照测试清单逐项测试，记录问题。

- [ ] **Step 3: 修复发现的问题**

根据测试结果修复 bug。

- [ ] **Step 4: 提交测试文档**

```bash
cd MoviePilot-Plugins
git add test_hdhivesearch_manual.md
git commit -m "test(hdhivesearch): add manual testing checklist"
```

---

## Task 13: 更新文档

**目标:** 更新 README.md 和相关文档

**Files:**
- Modify: `plugins.v2/hdhivesearch/README.md`
- Modify: `docs/V2_Plugin_Development.md`（如果需要）

- [ ] **Step 1: 更新 README.md**

在 `plugins.v2/hdhivesearch/README.md` 中添加新功能说明：

```markdown
## 功能特性

- 🔍 **资源搜索** - 通过影片名/TMDB ID搜索网盘资源
- 📋 **详情展示** - 显示资源大小、分辨率、字幕、来源等详细信息
- 🔓 **积分解锁** - 使用积分或VIP免费额度解锁资源
- 👤 **用户管理** - 查询积分、VIP状态
- ✅ **每日签到** - 签到获取积分
- 📊 **免费额度** - VIP用户查看每周免费解锁额度
- 📦 **CMS自动转存** - 115网盘资源自动转存到CloudSyncMedia（新增）
- 📈 **统计系统** - 搜索次数、转存次数、成功率统计（新增）
- 🔄 **智能重试** - 系统代理→直连双重访问机制（新增）
- 📱 **微信优化** - 支持微信企业应用消息格式化（新增）
- ⚙️ **优先级配置** - 自定义网盘资源优先级（新增）
- 👑 **Premium控制** - Premium用户权限管理（新增）

## v2.0.0 更新内容

### 新增功能
- **CMS自动转存**: 115网盘资源解锁后自动转存到CloudSyncMedia系统
- **统计系统**: 完整的搜索和转存统计，支持 `/hdhive_stats` 命令查询
- **智能重试**: 增强的网络请求重试机制，支持系统代理和直连自动切换
- **微信格式化**: 优化微信企业应用的消息显示格式
- **优先级配置**: 支持自定义115、123、夸克、百度网盘的显示优先级
- **Premium控制**: Premium用户专属功能的权限控制

### 配置说明
新增以下配置项：
- Premium用户开关
- 网盘优先级（4个优先级配置）
- CMS转存配置（启用开关、URL、用户名、密码）

## 使用方法

### 基本搜索
发送「影片名？」进行搜索，例如：
```
武林外传？
权力的游戏？
复仇者联盟？
```

### 查看详情
搜索结果后，回复数字查看详情：
```
1？      # 查看第1个资源详情
2？      # 查看第2个资源详情
```

### 指定网盘类型
```
1.115？   # 查看115网盘资源
1.quark？ # 查看夸克网盘资源
```

### 自动转存
如果启用了CMS转存，查看115网盘资源详情后会自动转存

### 用户命令
| 命令 | 说明 |
|------|------|
| /hdhive_me | 查看用户信息（Premium） |
| /hdhive_checkin | 每日签到（Premium） |
| /hdhive_quota | 查看免费额度（Premium） |
| /hdhive_search | 搜索资源 |
| /hdhive_stats | 查看插件统计（新增） |
```

- [ ] **Step 2: 提交文档更新**

```bash
cd MoviePilot-Plugins
git add plugins.v2/hdhivesearch/README.md
git commit -m "docs(hdhivesearch): update README for v2.0.0 with new features"
```

---

## Task 14: 最终检查和发布

**目标:** 最终代码检查、版本标记和发布

**Files:**
- All modified files

- [ ] **Step 1: 最终代码检查**

```bash
# 检查语法
python -m py_compile plugins.v2/hdhivesearch/*.py

# 检查代码风格（如果有配置）
# pycodestyle plugins.v2/hdhivesearch/

# 检查文件完整性
ls -la plugins.v2/hdhivesearch/
```

- [ ] **Step 2: 创建版本标签**

```bash
cd MoviePilot-Plugins
git tag -a v2.0.0 -m "HDHive插件 v2.0.0 - 重大功能更新"
git push origin v2.0.0
```

- [ ] **Step 3: 创建 Release Notes**

创建 `RELEASE_NOTES_v2.0.0.md`:

```markdown
# HDHive 资源搜索插件 v2.0.0 发布说明

## 发布日期
2025-03-19

## 重大更新

### 新增功能
1. **CMS自动转存**
   - 115网盘资源解锁后自动转存到CloudSyncMedia
   - 支持转存状态通知和统计
   - 可在插件配置中启用/禁用

2. **统计系统**
   - 搜索统计：总次数、成功/失败次数、成功率
   - 转存统计：转存次数、成功/失败次数、成功率
   - 时间记录：最后搜索和转存时间
   - 新增 `/hdhive_stats` 命令查询统计

3. **智能重试机制**
   - 系统代理失败自动切换到直连
   - HTTP错误分类处理（401/403/429等）
   - 最多重试3次，支持指数退避

4. **微信格式化**
   - 支持微信企业应用消息格式化
   - 优化换行和空行处理
   - 自动检测微信通知渠道

5. **网盘优先级配置**
   - 自定义115、123、夸克、百度网盘的显示优先级
   - 搜索结果按优先级排序
   - 支持指定网盘类型查看

6. **Premium用户控制**
   - Premium用户专属功能权限控制
   - 启动时验证VIP状态
   - 未授权用户友好提示

### 改进
- 完善错误处理和用户友好的错误消息
- 优化网络请求超时处理
- 改进日志记录
- 增强配置表单

### 配置变更
新增配置项：
- `is_premium_user`: Premium用户开关
- `priority_1/2/3/4`: 网盘优先级配置
- `cms_enabled`: CMS转存启用开关
- `cms_url`: CMS服务器地址
- `cms_username`: CMS用户名
- `cms_password`: CMS密码

### 兼容性
- MoviePilot V2.0+
- Python 3.10+
- 向后兼容 v1.x 配置

### 升级说明
1. 备份当前插件配置
2. 更新插件到 v2.0.0
3. 重新配置新增的配置项（可选）
4. 保存配置并重启插件

### 已知问题
- 无

### 下一步计划
- 支持更多网盘类型的自动转存
- 添加转存历史记录查询
- 支持批量转存
```

- [ ] **Step 4: 最终提交**

```bash
cd MoviePilot-Plugins
git add .
git commit -m "release(hdhivesearch): prepare for v2.0.0 release"
```

---

## 测试策略

### 单元测试
- CMS 客户端登录和转存功能
- HDHive API 重试逻辑
- 微信格式化逻辑
- 资源优先级排序

### 集成测试
- 完整工作流程：搜索→解锁→转存
- Premium 权限控制
- 错误处理和用户通知

### 手动测试
- 配置界面表单验证
- 微信企业应用消息显示
- 统计数据持久化

---

## 依赖项

### 外部依赖
- `requests>=2.31.0` - HTTP 客户端（已有）
- `urllib3` - HTTP 适配器（已有）
- MoviePilot V2 Plugin SDK
- MoviePilot MediaChain
- MoviePilot 事件系统

### 新增文件
- `plugins.v2/hdhivesearch/cms_client.py`

### 修改文件
- `plugins.v2/hdhivesearch/__init__.py`
- `plugins.v2/hdhivesearch/hdhive_api.py`
- `package.v2.json`

---

## 风险和注意事项

### 实施风险
1. **CMS 转存可能失败** - 网络问题、认证问题、容量限制
2. **HDHive API 频率限制** - 可能影响用户体验
3. **Premium 验证可能失败** - 网络延迟导致验证超时

### 缓解措施
1. 完善的错误处理和用户通知
2. 自动重试机制
3. 详细的日志记录
4. 用户友好的错误消息

### 兼容性
- 向后兼容 v1.x 配置
- 保留所有现有功能
- 新功能可选启用

---

## 完成标准

- [ ] 所有 Task 完成
- [ ] 代码语法检查通过
- [ ] 手动测试通过
- [ ] 文档更新完整
- [ ] 版本号更新正确
- [ ] Git 提交完整
- [ ] Release Notes 准备就绪

---

## 附录

### 相关文档
- [设计规范](../specs/2025-03-19-hdhive-plugin-enhancement-design.md)
- [HDHive Open API 文档](../../HDHive Open API 文档.txt)
- [Nullbr 资源搜索插件](../nullbr_search/)
- [MoviePilot V2 插件开发文档](../../MoviePilot-Plugins/docs/V2_Plugin_Development.md)

### 参考资料
- CloudSyncMedia API 文档（如有）
- MoviePilot 插件开发指南
- Vuetify 组件库文档

---

**计划创建日期:** 2025-03-19
**计划版本:** 1.0
**预计工作量:** 8-12 小时
**目标发布日期:** 2025-03-20
