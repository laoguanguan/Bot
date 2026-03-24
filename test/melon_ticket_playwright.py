import time
import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
from playwright.async_api import Browser, BrowserContext, Page, Response, async_playwright
import asyncio
# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MelonPlayWrightManager:
    def __init__(self):
        self.headless = False
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.cookies : List[Dict] = []
        
        # 登录账号密码
        self.username = "790877095@qq.com"
        self.password = "guanhr2728836"
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh,ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://ticket.melon.com/",
            "Origin": "https://ticket.melon.com"
        }
        
    async def start_browser(self):
        async with async_playwright() as p:
            self.browser = await p.chromium.launch(
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
            
            # 1. 确保你已经有一个带正确 UA 和 Referer 的 context
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="Asia/Seoul",
            )
            
            
            # page = await self.context.new_page()
            # login_url = "https://gmember.melon.com/login/login_form.htm" # 注意是登录页，不是处理页
            # await page.goto(login_url)
            # await page.wait_for_load_state("networkidle") 
            print(f"✅ 已访问登录页，当前 Cookie: {await self.context.cookies()}")
            
            # 2. 发起 POST 请求（注意是 async + await）
            resp: Response = await self.context.request.post(
                "https://gmember.melon.com/login/login_proc.htm",
                data={  # 👈 对应 requests 的 data=，会自动编码为 form-urlencoded
                    "rtnUrl": "https://tkglobal.melon.com/main/index.htm",
                    "langCd": "EN",
                    "email": self.username,
                    "pwd": self.password
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://tkglobal.melon.com/login/login.htm", 
                    "User-Agent": self.headers["User-Agent"]
                }
            )

            # 3. 检查响应
            if resp.status == 302 or (resp.status == 200 and "tkkglobal.melon.com" in resp.url):
                print("✅ 登录成功！")
            else:
                print(f"❌ 登录失败，状态码: {resp.status}")
        
        return
    
    async def close(self):
       
        if self.browser:
            await self.browser.close()
            self.browser = None
            self.context = None
            self.page = None
            
if __name__ == "__main__":
    manager = MelonPlayWrightManager()
    asyncio.run(manager.start_browser())