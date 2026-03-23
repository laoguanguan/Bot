import time
import os
from typing import Optional, Dict, List, Any
from datetime import datetime
from playwright.sync_api import sync_playwright

class MelonPlayWrightManager:
    def __init__(self):
        self.headless = True
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.cookies : Optional[Cookie] = None
    async def start_browser(self):
        """启动浏览器"""
        playwright = await async_playwright().start()
        # 启动 Chromium，生产环境建议 headless=True，调试时 False
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu"
            ]
        )
        
        # 创建上下文，设置标准的 User-Agent (必须与 curl_cffi 模拟的版本一致)
        # 这里模拟 Chrome 120
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="Asia/Seoul" # Melon 是韩国网站，时区设为首尔
        )
        # self.page = await self.context.new_page()
        
        # 1.登录
        resp = await self.context.post(
            "https://gmember.melon.com/login/login_proc.htm"，
            params={
                rtnUrl": "https://tkglobal.melon.com/main/index.htm",
                "langCd": "EN",
                "email": username,
                "pwd": password
            }
        )
        
        # 判断登录结果
        if resp.status == 302 or (resp.status == 200 and "tkgglobal.melon.com" in resp.url):
            if self._is_logged_in():
                logger.info("? 账号密码登录成功！")
                # 登录成功后，立即保存 Cookie
                self._save_cookies()
                return True
            else:
                logger.warning("?? 收到成功响应但未获取到 Cookie，登录可能未生效。")
                return False
        else:
            logger.error(f"? 登录失败。状态码: {resp.status}, 当前 URL: {resp.url}")
            return False

        except Exception as e:
            logger.error(f"? 登录请求异常: {e}")
            return False
        finally:
            browser.close()
        
        return
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            self.browser = None
            self.context = None
            self.page = None