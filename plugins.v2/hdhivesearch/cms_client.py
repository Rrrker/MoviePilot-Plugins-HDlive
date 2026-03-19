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
