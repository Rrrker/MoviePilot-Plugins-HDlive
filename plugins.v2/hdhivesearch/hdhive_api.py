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
    BASE_URL = "https://hdhive.com/api/open"
    
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
    
    def ping(self) -> Dict:
        return self._request_with_fallback("GET", "/ping")

    def get_user_info(self) -> Dict:
        return self._request_with_fallback("GET", "/me")

    def checkin(self) -> Dict:
        return self._request_with_fallback("POST", "/checkin")

    def get_quota(self) -> Dict:
        return self._request_with_fallback("GET", "/quota")

    def get_usage(self) -> Dict:
        return self._request_with_fallback("GET", "/usage")

    def get_today_usage(self) -> Dict:
        return self._request_with_fallback("GET", "/usage/today")

    def get_weekly_free_quota(self) -> Dict:
        return self._request_with_fallback("GET", "/vip/weekly-free-quota")
    
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
    
    def check_resource(self, url: str) -> Dict:
        return self._request_with_fallback("POST", "/check/resource", json={"url": url})

    def get_shares(self, page: int = 1, page_size: int = 20) -> Dict:
        return self._request_with_fallback("GET", "/shares", params={
            "page": page,
            "page_size": page_size
        })

    def get_share_detail(self, slug: str) -> Dict:
        """获取资源详情"""
        return self._request_with_fallback("GET", f"/shares/{slug}")

    def create_share(self, share_data: Dict) -> Dict:
        return self._request_with_fallback("POST", "/shares", json=share_data)

    def update_share(self, slug: str, share_data: Dict) -> Dict:
        return self._request_with_fallback("PATCH", f"/shares/{slug}", json=share_data)

    def delete_share(self, slug: str) -> Dict:
        return self._request_with_fallback("DELETE", f"/shares/{slug}")
    
    def close(self):
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
