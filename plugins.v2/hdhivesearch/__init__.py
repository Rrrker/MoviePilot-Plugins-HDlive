import re
import json
import time
from typing import Any, List, Dict, Optional, Tuple
from datetime import datetime

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, ChainEventType, NotificationType
from app.schemas import MediaType
from app.utils.http import RequestUtils

from .hdhive_api import HDHiveAPI, HDHiveException


class HDHiveSearch(_PluginBase):
    plugin_name = "HDHive资源搜索"
    plugin_desc = "通过HDHive API搜索网盘资源，支持115/123/夸克/百度网盘等。"
    plugin_icon = "Alist_B.png"
    plugin_version = "1.0.0"
    plugin_author = "HDHive"
    author_url = "https://hdhive.com"
    plugin_config_prefix = "hdhivesearch_"
    plugin_order = 10
    auth_level = 1

    _enabled = False
    _api_key = ""
    _api_base_url = "https://hdhive.com/api/open"
    _notify = True
    _search_history: Dict[str, Dict] = {}
    _user_cache: Dict[str, Any] = {}
    _api: Optional[HDHiveAPI] = None

    # Premium 用户配置
    _is_premium_user = False

    # 网盘优先级配置
    _priority_1 = "115"
    _priority_2 = "quark"
    _priority_3 = "123"
    _priority_4 = "baidu"

    # CMS 配置
    _cms_enabled = False
    _cms_url = ""
    _cms_username = ""
    _cms_password = ""
    _cms_client = None

    # 统计数据
    _stats = {
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
    _error_counts = {
        'api_timeout': 0,
        'api_auth_failed': 0,
        'cms_timeout': 0,
        'cms_auth_failed': 0,
        'insufficient_points': 0,
        'rate_limit_exceeded': 0,
    }

    def init_plugin(self, config: dict = None):
        self.stop_service()

        if config:
            self._enabled = config.get("enabled", False)
            self._api_key = config.get("api_key", "")
            self._api_base_url = config.get("api_base_url", "https://hdhive.com/api/open")
            self._notify = config.get("notify", True)
            self._search_history = config.get("search_history", {})
            self._user_cache = config.get("user_cache", {})

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

            # 加载错误统计
            self._error_counts = config.get("error_counts", self._error_counts)

        # 初始化 HDHive API
        if self._enabled and self._api_key:
            self._api = HDHiveAPI(
                api_key=self._api_key,
                base_url=self._api_base_url
            )

            # 验证 Premium 用户状态
            if self._is_premium_user:
                self._verify_premium_user()

            logger.info("HDHive资源搜索插件初始化成功")

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

    def _check_premium_access(self, feature_name: str) -> bool:
        """检查是否有权限访问Premium功能"""
        if not self._is_premium_user:
            logger.warning(f"尝试访问Premium功能 {feature_name} 被拒绝")
            return False
        return True

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/hdhive_search",
                "event": EventType.PluginAction,
                "desc": "HDHive资源搜索",
                "category": "资源搜索",
                "data": {"action": "hdhive_search"}
            },
            {
                "cmd": "/hdhive_me",
                "event": EventType.PluginAction,
                "desc": "HDHive用户信息",
                "category": "资源搜索",
                "data": {"action": "hdhive_me"}
            },
            {
                "cmd": "/hdhive_checkin",
                "event": EventType.PluginAction,
                "desc": "HDHive每日签到",
                "category": "资源搜索",
                "data": {"action": "hdhive_checkin"}
            },
            {
                "cmd": "/hdhive_quota",
                "event": EventType.PluginAction,
                "desc": "HDHive免费额度",
                "category": "资源搜索",
                "data": {"action": "hdhive_quota"}
            },
            {
                "cmd": "/hdhive_stats",
                "event": EventType.PluginAction,
                "desc": "HDHive插件统计",
                "category": "资源搜索",
                "data": {"action": "hdhive_stats"}
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/search",
                "endpoint": self.api_search,
                "methods": ["GET"],
                "summary": "搜索资源",
                "description": "通过TMDB ID搜索HDHive资源"
            },
            {
                "path": "/unlock",
                "endpoint": self.api_unlock,
                "methods": ["POST"],
                "summary": "解锁资源",
                "description": "使用积分解锁HDHive资源"
            },
            {
                "path": "/user",
                "endpoint": self.api_user_info,
                "methods": ["GET"],
                "summary": "用户信息",
                "description": "获取HDHive用户信息"
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
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
                                            "label": "启用插件",
                                            "hint": "开启后将监听用户消息进行资源搜索"
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
                                            "model": "notify",
                                            "label": "发送通知",
                                            "hint": "搜索结果发送消息通知"
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
                                            "model": "api_key",
                                            "label": "API Key",
                                            "type": "password",
                                            "placeholder": "输入HDHive API Key",
                                            "hint": "从HDHive官网获取API Key"
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
                                            "placeholder": "https://hdhive.com/api/open",
                                            "hint": "HDHive API服务地址"
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
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "text": "使用方法：发送「影片名？」进行搜索，如「武林外传？」。搜索结果以数字选择，如「1？」查看详情，「1.115？」指定网盘类型。"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": self._enabled,
            "api_key": self._api_key,
            "api_base_url": self._api_base_url,
            "notify": self._notify
        }

    def get_page(self) -> List[dict]:
        return [
            {
                "component": "VCard",
                "props": {
                    "title": "搜索历史",
                    "subtitle": "最近的搜索记录"
                },
                "content": [
                    {
                        "component": "VDataTable",
                        "props": {
                            "headers": [
                                {"title": "关键词", "key": "keyword"},
                                {"title": "搜索时间", "key": "time"},
                                {"title": "结果数", "key": "count"}
                            ],
                            "items": self._get_search_history_list(),
                            "items-per-page": 10
                        }
                    }
                ]
            }
        ]

    def _get_search_history_list(self) -> List[Dict]:
        result = []
        for keyword, data in self._search_history.items():
            result.append({
                "keyword": keyword,
                "time": data.get("time", ""),
                "count": data.get("count", 0)
            })
        return sorted(result, key=lambda x: x["time"], reverse=True)[:20]

    @eventmanager.register(EventType.PluginAction)
    def handle_plugin_action(self, event: Event):
        if not self._enabled or not self._api:
            return

        event_data = event.event_data
        if not event_data:
            return

        action = event_data.get("action")
        if not action or not action.startswith("hdhive_"):
            return

        channel = event_data.get("channel")
        userid = event_data.get("user")
        text = event_data.get("text", "")

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

    @eventmanager.register(EventType.UserMessage)
    def handle_user_message(self, event: Event):
        """
        监听用户消息，识别搜索请求和资源选择
        """
        if not self._enabled or not self._api:
            return

        event_data = event.event_data
        if not event_data:
            return

        # 获取消息内容
        text = event_data.get('text', '').strip()
        if not text:
            return

        channel = event_data.get('channel')
        userid = event_data.get('userid') or event_data.get('user')

        # 1. 检查是否为指定网盘类型（数字.网盘类型）- 最具体的模式要最先检查
        if re.match(r'^(\d+)\.(115|123|quark|baidu)[\?您]?$', text):
            match = re.match(r'^(\d+)\.(115|123|quark|baidu)', text)
            index = int(match.group(1))
            pan_type = match.group(2)
            self._handle_selection(channel, userid, index, pan_type)

        # 2. 检查是否为资源详情查看（纯数字）
        elif re.match(r'^(\d+)[\?您]?$', text):
            match = re.match(r'^(\d+)', text)
            index = int(match.group(1))
            self._handle_selection(channel, userid, index)

        # 3. 检查是否为搜索请求（以？或?结尾）- 最宽泛的模式放在最后
        elif text.endswith('?') or text.endswith('？'):
            keyword = text[:-1].strip()
            if keyword:
                logger.info(f'检测到搜索请求: {keyword}')
                self._handle_search(channel, userid, keyword)

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

    def _format_search_results(self, keyword: str, resources: List[Dict]) -> str:
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

    def _format_resource_detail(self, detail: Dict) -> str:
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
            f"最后验证: {last_validated}"
        ]

        return "\n".join(lines)

    def _handle_user_info(self, channel, userid):
        """处理用户信息查询（Premium功能）"""
        if not self._check_premium_access("用户信息查询"):
            self._send_message(channel, userid, "权限不足",
                "此功能需要Premium会员，请在插件配置中启用Premium用户选项")
            return

        if not self._api:
            return

        try:
            user_info = self._api.get_user_info()
            if not user_info:
                self._send_message(channel, userid, "错误", "获取用户信息失败，请检查API Key是否正确。")
                return

            nickname = user_info.get("nickname", "未知")
            is_vip = user_info.get("is_vip", False)
            vip_expire = user_info.get("vip_expiration_date", "无")
            points = user_info.get("user_meta", {}).get("points", 0)
            signin_days = user_info.get("user_meta", {}).get("signin_days_total", 0)
            share_num = user_info.get("user_meta", {}).get("share_num", 0)

            vip_status = f"✅ VIP (到期: {vip_expire})" if is_vip else "❌ 普通用户"

            message = [
                f"用户名: {nickname}",
                f"会员状态: {vip_status}",
                f"当前积分: {points}",
                f"累计签到: {signin_days}天",
                f"分享数量: {share_num}"
            ]

            self._send_message(channel, userid, "👤 用户信息", "\n".join(message))

        except HDHiveException as e:
            logger.error(f"获取用户信息失败: {e}")
            self._send_message(channel, userid, "错误", str(e))

    def _handle_checkin(self, channel, userid):
        """处理每日签到（Premium功能）"""
        if not self._check_premium_access("每日签到"):
            self._send_message(channel, userid, "权限不足",
                "此功能需要Premium会员，请在插件配置中启用Premium用户选项")
            return

        if not self._api:
            return

        try:
            result = self._api.checkin()
            message = result.get("message", "签到成功")
            points = result.get("points", 0)
            total_days = result.get("total_days", 0)

            self._send_message(
                channel, userid, "✅ 签到成功",
                f"{message}\n获得积分: {points}\n累计签到: {total_days}天"
            )

        except HDHiveException as e:
            logger.error(f"签到失败: {e}")
            self._send_message(channel, userid, "签到失败", str(e))

    def _handle_quota(self, channel, userid):
        """处理免费额度查询（Premium功能）"""
        if not self._check_premium_access("免费额度查询"):
            self._send_message(channel, userid, "权限不足",
                "此功能需要Premium会员，请在插件配置中启用Premium用户选项")
            return

        if not self._api:
            return

        try:
            quota = self._api.get_weekly_free_quota()
            is_forever_vip = quota.get("is_forever_vip", False)
            limit = quota.get("limit", 0)
            used = quota.get("used", 0)
            remaining = quota.get("remaining", 0)
            unlimited = quota.get("unlimited", False)

            if not is_forever_vip:
                message = "您不是VIP用户，无法使用免费额度功能。"
            elif unlimited:
                message = f"永久VIP用户，无限制解锁官方资源。\n已使用: {used}次"
            else:
                message = f"每周免费额度: {limit}次\n已使用: {used}次\n剩余: {remaining}次"

            self._send_message(channel, userid, "📊 免费额度", message)

        except HDHiveException as e:
            logger.error(f"获取免费额度失败: {e}")
            self._send_message(channel, userid, "错误", str(e))

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

    def _show_help(self, channel, userid):
        help_text = """
📖 HDHive资源搜索使用说明

🔍 搜索资源:
   发送「影片名？」进行搜索
   例如: 武林外传？

📋 查看详情:
   回复数字查看资源详情
   例如: 1？

🎯 指定网盘:
   回复「数字.网盘类型？」
   例如: 1.115？

🔓 解锁资源:
   查看详情后回复「解锁」

👤 用户命令:
   /hdhive_me - 查看用户信息
   /hdhive_checkin - 每日签到
   /hdhive_quota - 查看免费额度
   /hdhive_stats - 查看插件统计

📌 支持网盘:
   115、123、夸克、百度、ed2k等
"""
        self._send_message(channel, userid, "帮助", help_text)

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
                message = f"""✅ 转存成功

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

    def _update_transfer_success_rate(self):
        """更新转存成功率"""
        total = self._stats['cms_transfers']
        if total > 0:
            successful = self._stats['successful_transfers']
            self._stats['transfer_success_rate'] = round((successful / total) * 100, 2)

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

        # 保存错误统计
        self.__update_config()

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

        # 保存错误统计
        self.__update_config()

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

    def _send_message(self, channel, userid, title: str, text: str):
        if self._notify:
            self.post_message(
                channel=channel,
                title=title,
                text=text,
                userid=userid
            )

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

            # 错误统计
            "error_counts": self._error_counts,

            # 搜索历史
            "search_history": self._search_history,
            "user_cache": self._user_cache
        })

    def stop_service(self):
        pass

    def api_search(self, tmdb_id: str, media_type: str = "movie"):
        if not self._api:
            return {"success": False, "message": "插件未启用或API未配置"}
        
        try:
            resources = self._api.get_resources(media_type, tmdb_id)
            return {"success": True, "data": resources}
        except HDHiveException as e:
            return {"success": False, "message": str(e)}

    def api_unlock(self, slug: str):
        if not self._api:
            return {"success": False, "message": "插件未启用或API未配置"}
        
        try:
            result = self._api.unlock_resource(slug)
            return {"success": True, "data": result}
        except HDHiveException as e:
            return {"success": False, "message": str(e)}

    def api_user_info(self):
        if not self._api:
            return {"success": False, "message": "插件未启用或API未配置"}
        
        try:
            user_info = self._api.get_user_info()
            return {"success": True, "data": user_info}
        except HDHiveException as e:
            return {"success": False, "message": str(e)}
