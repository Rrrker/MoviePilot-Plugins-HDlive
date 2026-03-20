import json
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.log import logger


class HDHiveException(Exception):
    def __init__(self, code: str, message: str, description: str = ""):
        self.code = code
        self.message = message
        self.description = description
        super().__init__(f"[{code}] {message}: {description}")


class HDHiveAPI:
    BASE_URL = "https://hdhive.com/api/open/"  # 末尾加斜杠，确保urljoin正确拼接
    
    ERROR_CODES = {
        "MISSING_API_KEY": "缺少API Key",
        "INVALID_API_KEY": "无效的API Key",
        "DISABLED_API_KEY": "API Key已被禁用",
        "EXPIRED_API_KEY": "API Key已过期",
        "VIP_REQUIRED": "需要VIP会员",
        "ENDPOINT_DISABLED": "接口已被禁用",
        "ENDPOINT_QUOTA_EXCEEDED": "接口每日调用额度已用尽",
        "RATE_LIMIT_EXCEEDED": "请求过于频繁",
    }
    
    def __init__(self, api_key: str, base_url: str = None, timeout: int = 30, use_proxy: bool = True, proxy_url: str = None):
        self.api_key = api_key
        self.base_url = base_url or self.BASE_URL
        # 确保 base_url 以 / 结尾，保证 urljoin 正确拼接
        if self.base_url and not self.base_url.endswith('/'):
            self.base_url = self.base_url + '/'
        self.timeout = timeout
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url

        # 配置请求会话
        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

        # 如果提供了代理地址，配置代理
        if self.proxy_url:
            self.session.proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url
            }
            logger.info(f"已配置代理: {self.proxy_url}")
        elif self.use_proxy:
            # 未提供代理地址但启用代理，尝试使用环境变量
            import os
            http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
            https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            if http_proxy or https_proxy:
                self.session.proxies = {}
                if http_proxy:
                    self.session.proxies["http"] = http_proxy
                if https_proxy:
                    self.session.proxies["https"] = https_proxy
                logger.info(f"使用环境变量代理: http={http_proxy}, https={https_proxy}")
            else:
                logger.warning("未找到环境变量代理 (HTTP_PROXY/HTTPS_PROXY)")

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
    
    def _request_with_fallback(self, method: str, endpoint: str, **kwargs) -> Dict:
        """
        发起HTTP请求，根据 use_proxy 配置决定是否使用代理
        启用代理时只使用代理，不自动回退直连
        """
        url = urljoin(self.base_url, endpoint)
        logger.info(f"完整请求URL: {url}")  # 添加调试日志

        # 如果不启用代理，直接直连
        if not self.use_proxy:
            logger.info("代理已禁用，直接连接HDHive API")
            # 创建临时会话，明确禁用代理
            direct_session = requests.Session()
            direct_session.headers.update(self.session.headers)
            direct_session.proxies = {'http': None, 'https': None}

            try:
                response = direct_session.request(
                    method=method,
                    url=url,
                    timeout=self.timeout,
                    **kwargs
                )
                logger.info(f"直连请求响应，状态码: {response.status_code}")
                return self._process_response(response)
            except Exception as e:
                logger.error(f"直连请求失败: {str(e)}")
                raise HDHiveException("NETWORK_ERROR", str(e))

        # 启用代理时，只使用代理
        if self.session.proxies:
            logger.info(f"使用代理访问HDHive API: {self.session.proxies}")
        else:
            logger.warning("代理已启用但未配置代理地址，尝试直连")
        response = self.session.request(
            method=method,
            url=url,
            timeout=self.timeout,
            **kwargs
        )
        logger.info(f"代理请求响应，状态码: {response.status_code}")
        return self._process_response(response)

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

        # 检查403禁止访问
        if response.status_code == 403:
            # 尝试获取响应内容用于调试
            response_text = response.text[:200] if response.text else "空响应"
            logger.error(f"API返回403 Forbidden，响应内容: {response_text}")
            raise HDHiveException(
                "FORBIDDEN",
                "访问被拒绝",
                f"API返回403错误，可能是代理问题或API Key无效。建议关闭代理开关尝试直连。"
            )

        # 检查其他错误状态码
        if response.status_code >= 400:
            response_text = response.text[:200] if response.text else "空响应"
            logger.error(f"API返回错误状态码 {response.status_code}，响应内容: {response_text}")
            raise HDHiveException(
                "HTTP_ERROR",
                f"HTTP错误 {response.status_code}",
                f"服务器返回错误: {response_text}"
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
    
    def ping(self) -> Dict:
        return self._request_with_fallback("GET", "ping")

    def get_user_info(self) -> Dict:
        return self._request_with_fallback("GET", "me")

    def checkin(self) -> Dict:
        return self._request_with_fallback("POST", "checkin")

    def get_quota(self) -> Dict:
        return self._request_with_fallback("GET", "quota")

    def get_usage(self) -> Dict:
        return self._request_with_fallback("GET", "usage")

    def get_today_usage(self) -> Dict:
        return self._request_with_fallback("GET", "usage/today")

    def get_weekly_free_quota(self) -> Dict:
        return self._request_with_fallback("GET", "vip/weekly-free-quota")

    def get_resources(self, media_type: str, tmdb_id: str) -> List[Dict]:
        """通过 TMDB ID 获取资源列表"""
        endpoint = f"resources/{media_type}/{tmdb_id}"
        result = self._request_with_fallback("GET", endpoint)

        if isinstance(result, dict) and "data" in result:
            return result.get("data", [])
        return result if isinstance(result, list) else []

    def unlock_resource(self, slug: str) -> Dict:
        """解锁资源"""
        return self._request_with_fallback("POST", "resources/unlock", json={"slug": slug})

    def check_resource(self, url: str) -> Dict:
        return self._request_with_fallback("POST", "check/resource", json={"url": url})

    def get_shares(self, page: int = 1, page_size: int = 20) -> Dict:
        return self._request_with_fallback("GET", "shares", params={
            "page": page,
            "page_size": page_size
        })

    def get_share_detail(self, slug: str) -> Dict:
        """获取资源详情"""
        return self._request_with_fallback("GET", f"shares/{slug}")

    def create_share(self, share_data: Dict) -> Dict:
        return self._request_with_fallback("POST", "shares", json=share_data)

    def update_share(self, slug: str, share_data: Dict) -> Dict:
        return self._request_with_fallback("PATCH", f"shares/{slug}", json=share_data)

    def delete_share(self, slug: str) -> Dict:
        return self._request_with_fallback("DELETE", f"shares/{slug}")
    
    def close(self):
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
