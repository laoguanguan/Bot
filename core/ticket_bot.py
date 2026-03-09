import time
import random
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, TimeoutError, ElementHandle, BrowserContext

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TicketBotConfig:
    """抢票配置类"""
    def __init__(
        self,
        target_url: str,
        open_time: str,  # 格式 "YYYY-MM-DD HH:MM:SS"
        seat_keywords: List[str] = ["A", "B", "1", "2"], # 优先选择的区域关键词
        max_retries: int = 50,
        retry_delay: float = 0.3, # 基础重试延迟 (秒)
        fast_refresh_interval: float = 0.5 # 开售前刷新间隔
    ):
        self.target_url = target_url
        self.open_time = datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
        self.seat_keywords = seat_keywords
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.fast_refresh_interval = fast_refresh_interval

class TicketBot:
    def __init__(self, context: BrowserContext, config: TicketBotConfig):
        self.context = context
        self.page = context.new_page()
        self.config = config
        self.is_running = False
        self.success = False
        
        # 设置视口和 userAgent (模拟真实设备)
        self.page.set_viewport_size({"width": 1920, "height": 1080})
        
        # 拦截部分资源加速加载 (可选)
        self.page.route("**/*.{png,jpg,jpeg,css,woff2}", lambda route: route.abort())

    def _wait_for_open_time(self):
        """倒计时等待开售"""
        logger.info(f"⏳ 等待开售时间: {self.config.open_time}")
        while True:
            now = datetime.now()
            diff = (self.config.open_time - now).total_seconds()
            
            if diff <= 0:
                logger.info("🚀 开售时间已到！开始行动！")
                break
            
            if diff > 10:
                # 剩余时间较长，休眠久一点
                sleep_time = min(diff, 5.0)
                logger.info(f"💤 还有 {diff:.1f} 秒，休眠 {sleep_time:.1f} 秒...")
                time.sleep(sleep_time)
            else:
                # 最后10秒，高频检查
                time.sleep(0.1)
        
        # 确保页面已加载目标 URL
        if self.page.url != self.config.target_url:
            logger.info(f"🌐 跳转至目标页面: {self.config.target_url}")
            self.page.goto(self.config.target_url, wait_until="domcontentloaded")

    def _handle_try_again_popup(self) -> bool:
        """
        处理 Melon 常见的 'Try Again' 或 '忙碌' 弹窗
        返回 True 表示检测并关闭了弹窗，需要重试
        """
        try:
            # 常见的弹窗关键词或选择器 (需根据实际页面调整)
            popup_selectors = [
                "button:has-text('확인')", 
                "button:has-text('Close')",
                ".alert_layer button",
                "text=Try Again",
                "text=잠시 후 다시 시도해주세요" # 韩语：请稍后重试
            ]
            
            for selector in popup_selectors:
                if self.page.is_visible(selector, timeout=500):
                    logger.warning(f"⚠️ 检测到阻碍弹窗，正在关闭: {selector}")
                    self.page.click(selector)
                    time.sleep(0.2)
                    return True
            return False
        except Exception:
            return False

    def _select_seat_smart(self) -> bool:
        """
        智能选座逻辑
        1. 查找包含关键词的座位/区域
        2. 点击第一个可用的
        """
        try:
            # 策略 A: 直接查找包含关键词的按钮 (Melon 通常是 <a> 或 <button>)
            for keyword in self.config.seat_keywords:
                # 构造 XPath 或 text 选择器
                selector = f"text={keyword}"
                elements = self.page.query_selector_all(selector)
                
                for el in elements:
                    if el.is_visible():
                        # 检查是否禁用 (Melon 已售出座位通常有 disabled 类或属性)
                        class_name = el.get_attribute("class") or ""
                        if "disabled" in class_name or "sold" in class_name:
                            continue
                        
                        logger.info(f"✅ 发现可用座位/区域: {keyword}")
                        el.click()
                        time.sleep(0.3) # 点击后稍作等待
                        return True
            
            # 策略 B: 如果没有关键词，尝试点击第一个未被禁用的座位 (激进模式)
            # all_seats = self.page.query_selector_all(".seat_table a") 
            # ... (此处可补充通用逻辑)
            
            return False
        except Exception as e:
            logger.error(f"❌ 选座过程出错: {e}")
            return False

    def _submit_reservation(self) -> bool:
        """
        提交预约/下一步
        通常点击 "다음" (Next) 或 "예매하기" (Book)
        """
        try:
            next_buttons = [
                "button:has-text('다음')",
                "button:has-text('예매하기')",
                ".btn_next",
                "#btnNext"
            ]
            
            for selector in next_buttons:
                if self.page.is_visible(selector, timeout=500):
                    logger.info("🔘 点击【下一步/预约】按钮")
                    self.page.click(selector)
                    time.sleep(1.0)
                    return True
            return False
        except Exception:
            return False

    def run(self):
        """主运行循环"""
        self.is_running = True
        logger.info("🤖 Melon 抢票机器人启动...")
        
        try:
            # 1. 预先加载页面 (避免开售时才加载)
            logger.info(f"🌐 预加载页面: {self.config.target_url}")
            self.page.goto(self.config.target_url, wait_until="domcontentloaded", timeout=60000)
            
            # 2. 等待开售时间
            self._wait_for_open_time()
            
            # 3. 进入抢票循环
            retry_count = 0
            while self.is_running and not self.success:
                retry_count += 1
                
                # 刷新页面 (Melon 往往需要不断刷新才能看到新库存)
                if retry_count % 3 == 0: # 每3次循环刷新一次，防止过于频繁被封，也可每次刷新
                     logger.info("🔄 刷新页面获取最新库存...")
                     self.page.reload(wait_until="domcontentloaded")
                     time.sleep(1.0) # 等待页面稳定

                # 处理弹窗
                if self._handle_try_again_popup():
                    logger.info(f"↩️ 遇到阻碍，第 {retry_count} 次重试...")
                    time.sleep(self.config.retry_delay)
                    continue

                # 尝试选座
                if self._select_seat_smart():
                    logger.info("🎫 座位选中，尝试提交...")
                    time.sleep(0.5)
                    
                    # 再次检查是否有弹窗阻挡提交
                    if not self._handle_try_again_popup():
                        if self._submit_reservation():
                            logger.success("🎉 提交成功！进入支付流程！")
                            self.success = True
                            break
                        else:
                            logger.warning("⚠️ 未找到提交按钮，可能已被抢占，继续重试...")
                    else:
                        continue # 有弹窗，下一轮循环处理
                else:
                    # 没选到座
                    if retry_count % 10 == 0:
                        logger.info(f"🔍 尚未找到座位，持续搜索中... (尝试次数: {retry_count})")
                    time.sleep(self.config.retry_delay)
                
                # 安全熔断：防止死循环
                if retry_count >= self.config.max_retries:
                    logger.error("🛑 达到最大重试次数，停止运行。")
                    break

        except TimeoutError:
            logger.error("⏱️ 页面加载超时，网络可能不稳定。")
        except Exception as e:
            logger.exception(f"💥 发生严重错误: {e}")
        finally:
            self.is_running = False
            if self.success:
                logger.info("✅ 任务完成，请手动完成后续支付验证（如 OTP）。")
            else:
                logger.info("❌ 任务结束，未抢到票。")
            
            # 可选：成功后保持浏览器打开以便人工介入支付
            # if self.success:
            #     time.sleep(300) 

    def stop(self):
        """外部停止信号"""
        logger.info("🛑 收到停止信号...")
        self.is_running = False