import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from playwright.sync_api import BrowserContext, Page, TimeoutError, Browser

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, browser: Browser, account_id: str, storage_dir: str = "./sessions"):
        self.browser = browser
        self.account_id = account_id
        self.storage_dir = Path(storage_dir)
        self.storage_file = self.storage_dir / f"{account_id}_session.json"
        
        # 确保目录存在
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Melon 特定的配置
        self.melon_url = "https://www.melon.com"
        self.login_url = "https://www.melon.com/my/index.htm" # 登录后通常会跳转这里
        
        # 韩国环境配置
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.locale = "ko-KR"
        self.timezone = "Asia/Seoul"

    def load_or_create_context(self) -> BrowserContext:
        """
        尝试加载已保存的 Session，如果失败或过期则创建新上下文并引导登录
        """
        logger.info(f"🔍 正在加载账号 [{self.account_id}] 的会话...")
        
        context = self.browser.new_context(
            user_agent=self.user_agent,
            locale=self.locale,
            timezone_id=self.timezone,
            viewport={"width": 1920, "height": 1080},
            # 禁用部分指纹检测特征 (可选，视反爬强度调整)
            bypass_csp=True 
        )

        # 尝试加载存储状态
        if self.storage_file.exists():
            try:
                logger.info(f"📂 发现本地会话文件: {self.storage_file}")
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                
                # 添加 Cookies
                if 'cookies' in state:
                    context.add_cookies(state['cookies'])
                    logger.info("✅ Cookies 已加载")
                
                # 添加 LocalStorage (Melon 有时将 Token 存在 LocalStorage)
                # 注意：Playwright add_cookies 不处理 LS，需通过页面注入或单独处理
                # 这里我们主要依赖 Cookies，LS 可以在登录后自动产生，或者手动保存/恢复
                
                # 验证会话是否有效
                if self._validate_session(context):
                    logger.success("🎉 会话验证成功，无需重新登录！")
                    return context
                else:
                    logger.warning("⚠️ 会话已过期或无效，将重新登录...")
                    # 清除无效 cookies 以防干扰
                    context.clear_cookies()
                    
            except Exception as e:
                logger.error(f"❌ 读取会话文件失败: {e}")
                if 'cookies' in locals(): context.clear_cookies()

        # 需要重新登录
        logger.info("🔐 开始执行登录流程...")
        self._perform_login(context)
        
        # 登录成功后保存状态
        self._save_session(context)
        return context

    def _validate_session(self, context: BrowserContext) -> bool:
        """
        验证当前 Session 是否有效
        策略：访问个人中心或 Melon Ticket 页面，检查是否包含登录用户信息
        """
        page = context.new_page()
        try:
            # 访问 Melon 主页或个人中心
            page.goto(self.melon_url, wait_until="domcontentloaded", timeout=15000)
            
            # 等待一小会儿让 JS 执行
            time.sleep(2)
            
            # 检测关键词：如果页面包含 "로그인" (Login) 按钮，说明未登录
            # 或者检测是否有用户昵称
            is_logged_in = False
            
            # 方法 1: 检查是否存在登出按钮或用户信息区域 (选择器需根据实际页面调整)
            # 常见的 Melon 登录态标识：头部显示 "홍길동님" 或 "MY" 菜单高亮
            if page.is_visible("text=로그아웃", timeout=3000): # 如果有登出按钮，说明已登录
                is_logged_in = True
            elif page.is_visible(".btn_logout", timeout=3000):
                is_logged_in = True
            # 方法 2: 检查是否被重定向回登录页
            elif "login" in page.url.lower():
                is_logged_in = False
            else:
                # 保守策略：如果没有明确的登出按钮，尝试访问 Ticket 页面看是否受限
                page.goto("https://ticket.melon.com/mypage/ticketList.htm", wait_until="domcontentloaded", timeout=10000)
                if "login" not in page.url.lower():
                    is_logged_in = True

            logger.info(f"🔍 会话验证结果: {'有效' if is_logged_in else '无效'} (当前 URL: {page.url})")
            return is_logged_in
            
        except TimeoutError:
            logger.error("⏱️ 验证会话超时")
            return False
        except Exception as e:
            logger.error(f"❌ 验证过程出错: {e}")
            return False
        finally:
            page.close()

    def _perform_login(self, context: BrowserContext):
        """
        执行登录操作
        注意：此处不自动填写密码（为了安全及应对验证码），而是打开页面让人工登录
        """
        page = context.new_page()
        
        try:
            logger.info("🌐 打开 Melon 登录页面...")
            page.goto("https://www.melon.com/my/index.htm", wait_until="domcontentloaded")
            
            # 提示用户操作
            print("\n" + "="*50)
            print("👉 请在弹出的浏览器窗口中手动完成登录！")
            print("   - 输入账号密码")
            print("   - 完成 OTP 或 滑块验证码")
            print("   - 确保登录成功后停留在主页")
            print("⏳ 脚本将在检测到登录成功后自动继续...")
            print("="*50 + "\n")
            
            # 轮询检测登录状态
            max_wait_time = 300  # 最多等待 5 分钟
            start_time = time.time()
            
            while time.time() - start_time < max_wait_time:
                time.sleep(2)
                
                # 检查 URL 是否变化（例如从 login 跳到了 index）
                if "login" not in page.url.lower() and "melon.com" in page.url:
                    # 双重确认：检查是否有登出按钮
                    if page.is_visible("text=로그아웃", timeout=2000) or page.is_visible(".btn_logout", timeout=2000):
                        logger.success("✅ 检测到用户已手动登录成功！")
                        break
                
                # 可选：检测特定的错误信息或验证码出现，给予提示
                if page.is_visible("text=아이디 또는 비밀번호를 잘못 입력했습니다", timeout=1000):
                    logger.warning("⚠️ 检测到账号密码错误提示，请重试。")

            else:
                logger.error("❌ 等待登录超时，请检查网络或手动操作是否完成。")
                raise TimeoutError("手动登录超时")

        except Exception as e:
            logger.error(f"💥 登录流程异常: {e}")
            raise e
        finally:
            # 登录完成后，页面可以关闭，Context 会保留 Cookies
            # 但为了防止意外，我们可以再停留一秒让数据写入
            time.sleep(1)
            page.close()

    def _save_session(self, context: BrowserContext):
        """
        保存当前的 Cookies 到本地文件
        """
        try:
            cookies = context.cookies()
            
            # 过滤掉一些不必要的临时 cookie (可选)
            # 这里保存所有 cookie 以确保完整性
            
            session_data = {
                "account_id": self.account_id,
                "saved_at": time.time(),
                "cookies": cookies
                # 如果需要保存 LocalStorage，需要遍历 pages 获取，比较复杂，通常 Cookies 足够
            }
            
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
            
            logger.success(f"💾 会话已保存至: {self.storage_file}")
            
        except Exception as e:
            logger.error(f"❌ 保存会话失败: {e}")

    def clear_session(self):
        """
        删除本地保存的会话文件（用于强制重新登录）
        """
        if self.storage_file.exists():
            self.storage_file.unlink()
            logger.info(f"🗑️ 已删除会话文件: {self.storage_file}")
        else:
            logger.info("ℹ️ 未发现会话文件")

# ==========================================
# 使用示例 (可以在 main.py 中调用)
# ==========================================
if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    
    ACCOUNT = "my_melon_account" # 替换为你的账号标识
    
    with sync_playwright() as p:
        # 启动浏览器 (必须有头模式，方便人工登录)
        browser = p.chromium.launch(headless=False)
        
        manager = SessionManager(browser, account_id=ACCOUNT)
        
        try:
            # 获取已登录的 Context
            context = manager.load_or_create_context()
            
            # 测试：访问一个需要登录的页面
            page = context.new_page()
            page.goto("https://ticket.melon.com/mypage/ticketList.htm")
            page.wait_for_load_state("networkidle")
            
            print(f"当前页面标题: {page.title()}")
            print("✅ 会话管理测试成功！你可以在此基础上运行抢票脚本。")
            
            # 保持浏览器打开一会儿供观察
            time.sleep(5)
            
        except Exception as e:
            logger.error(f"测试失败: {e}")
        finally:
            browser.close()