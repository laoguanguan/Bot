# import requests
import time
import os
import hashlib
import json
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
from curl_cffi import requests
from datetime import datetime

COOKIE_FILE = "melon_cookies.json"

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_melon_timestamp() -> str:
    now = datetime.now()
    # 格式：年月日时分秒 + 毫秒（三位）
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"

class MelonTicketClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.impersonate = "chrome120"
        # 设置通用 Headers (模拟浏览器)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://ticket.melon.com/",
            "Origin": "https://ticket.melon.com"
        }
        self.session.headers.update(self.headers)
        
        # 关键状态变量
        self.auth_token = None
        self.user_id = None
        self.prod_id = None       # 演出 ID
        self.place_id = None      # 场馆 ID
        self.perf_id = None       # 场次 ID (具体日期时间)
        self.ticket_area_id = None # 区域 ID
        self.ticket_seat_info = None # 选座信息
        
        # TODO: 根据文档填入基础 URL
        self.BASE_URL = "https://tkglobal.melon.com" # 示例，需替换为文档中的真实 Base URL

    def _save_cookies(self):
        """将当前 Session 的 Cookie 保存到本地文件"""
        cookies = self.session.cookies.get_dict()
        if cookies:
            with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cookies, f)
            logger.info(f"💾 Cookie 已保存至 {COOKIE_FILE}")
        else:
            logger.warning("⚠️ 没有可保存的 Cookie")

    def _load_cookies(self):
        """从本地文件加载 Cookie 到 Session"""
        if os.path.exists(COOKIE_FILE):
            try:
                with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                self.session.cookies.update(cookies)
                logger.info(f"✅ 已从 {COOKIE_FILE} 加载 Cookie")
                return True
            except Exception as e:
                logger.error(f"❌ 加载 Cookie 失败: {e}")
                if os.path.exists(COOKIE_FILE):
                    os.remove(COOKIE_FILE) # 删除损坏的文件
        else:
            logger.info("📂 未找到 Cookie 文件，需要重新登录")
        return False

    def _is_logged_in(self) -> bool:
        """
        验证当前 Cookie 是否有效
        策略：访问一个需要登录才能查看的接口（例如用户信息或购票列表）
        """
        # 这里选择一个通常需要先登录才能访问的 URL 进行测试
        # 注意：Melon Global 的具体 API 可能需要调整，这里用 MyPage 或类似的作为示例
        islogin_url = "https://tkglobal.melon.com/main/ajax/isLogin.json"   
        
        try:
            resp = self.session.post(islogin_url)
            
            # 判断逻辑：
            # 1. 如果状态码是 200 且页面包含用户相关信息，说明登录有效
            # 2. 如果被重定向 (302) 到登录页，说明 Cookie 失效
            # 3. 如果返回内容包含 "login" 关键字，说明未登录
            
            if resp.status_code == 200 :
                 # 尝试将响应解析为 JSON
                json_data = resp.json()
                
                # 关键判断：检查 JSON 中的 result 字段
                # 假设 {"result": 0} 代表成功/已登录
                if json_data.get("result") == 0:
                    logger.info("✅ Cookie 验证通过 (API 返回 result=0)，登录状态有效")
                    return True
                else:
                    # result 不为 0，通常是错误码，代表未登录或 token 失效
                    error_msg = json_data.get("message", "未知错误")
                    logger.warning(f"⚠️ Cookie 已失效 (API 返回 result={json_data.get('result')}, 消息: {error_msg})")
                    return False
            else:
                logger.warning(f"⚠️ Cookie 已失效 (状态码: {resp.status_code}, 跳转至: {resp.url})")
                return False
                
        except Exception as e:
            logger.error(f"❌ 验证 Cookie 时发生网络错误: {e}")
            return False

    # ================= 步骤 1: 登录与认证 (已重构) =================
    def login(self, username: str, password: str, otp_code: Optional[str] = None) -> bool:
        """
        用户登录主入口：
        1. 优先尝试使用本地 Cookie
        2. 如果 Cookie 无效或不存在，则执行账号密码登录
        """
        logger.info("🔐 正在检查登录状态...")
        
        # 1. 尝试加载本地 Cookie
        if self._load_cookies():
            # 2. 验证 Cookie 是否有效
            if self._is_logged_in():
                logger.info("🚀 使用本地 Cookie 自动登录成功！跳过密码登录步骤。")
                return True
            else:
                logger.warning("⚠️ 本地 Cookie 已失效，将尝试重新登录...")
                # 可选：删除失效的 cookie 文件
                if os.path.exists(COOKIE_FILE):
                    os.remove(COOKIE_FILE)

        # 3. 执行账号密码登录流程
        logger.info("🔑 正在执行账号密码登录...")
        url = "https://gmember.melon.com/login/login_proc.htm"
        
        payload = {
            "rtnUrl": "https://tkglobal.melon.com/main/index.htm",
            "langCd": "EN",
            "email": username,
            "pwd": password
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://tkglobal.melon.com/login/login.htm", 
            "User-Agent": self.headers["User-Agent"]
        }

        try:
            resp = self.session.post(url, data=payload, headers=headers)
            
            # 判断登录结果
            if resp.status_code == 302 or (resp.status_code == 200 and "tkglobal.melon.com" in resp.url):
                if self.session.cookies.get_dict():
                    logger.info("✅ 账号密码登录成功！")
                    # 4. 登录成功后，立即保存 Cookie
                    self._save_cookies()
                    self._is_logged_in() # 再次验证登录状态，确保 Cookie 已生效
                    return True
                else:
                    logger.warning("⚠️ 收到成功响应但未获取到 Cookie，登录可能未生效。")
                    return False
            else:
                logger.error(f"❌ 登录失败。状态码: {resp.status_code}, 当前 URL: {resp.url}")
                # 调试用：打印部分响应内容
                # logger.debug(f"响应预览: {resp.text[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"💥 登录请求异常: {e}")
            return False
    # ================= 步骤 1.3: 获取演出详情与场次 =================
    def get_member_key_info(self) -> int:
        """
        获取用户的 MemberKey 和 UserId
        这是登录后的第一步，后续接口调用都需要这个 UserId
        """
        url = "https://tkglobal.melon.com/member/getMemberKey.json"
        self.member_key = None
       
        resp = self.session.get(url)
        resp.raise_for_status()
        data = resp.json()
        
        return self.member_key

    # ================= 步骤 2: 获取演出详情与场次 =================
    def get_performance_details(self, prod_id: str) -> Dict:
        """
        获取演出详情，包含所有场次 (PerfId) 列表
        """
        self.prod_id = prod_id
        logger.info(f"🎭 获取演出详情: {prod_id}")
        
        # TODO: 填入文档中的演出详情接口 URL
        url = "https://tkglobal.melon.com/tktapi/glb/product/schedule/daylist.json"
        
        params = {
            "callback": "scheduleList2",
            "prodId": prod_id,
            "pocCode": "SC0002",
            "perfTypeCode": "GN0001",
            "sellTypeCode": "ST0001",
            "langCd": "EN",
            "prodTypeCode": "PT0001",
            "interlockTypeCode": "",
            "v" : 1,
            "timestamp": generate_melon_timestamp()
        }
        
        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            text = resp.text
            data = resp.json()
            
            # TODO: 解析场次列表
            # 假设返回结构中有 performanceList -> [{perfId, date, time, status}]
            performances = data["data"]["performanceList"] 
            
            # 筛选可购买的场次 (status == 'ON_SALE' 或类似)
            available_perfs = [p for p in performances if p["status"] == "ON_SALE"]
            
            if not available_perfs:
                logger.warning("⚠️ 暂无可售场次")
                return {}
            
            # 策略：选择第一个可用场次，或根据时间筛选
            target_perf = available_perfs[0] 
            self.perf_id = target_perf["perfId"]
            self.place_id = target_perf.get("placeId")
            
            logger.info(f"✅ 选定场次: PerfId={self.perf_id}, 时间={target_perf.get('date')}")
            return target_perf
            
        except Exception as e:
            logger.error(f"💥 获取演出详情失败: {e}")
            return {}

    # ================= 步骤 3: 查询余票与区域 (Seat Map) =================
    def check_ticket_availability(self) -> List[Dict]:
        """
        查询当前场次的余票情况，获取可买的区域 (Area)
        """
        if not self.perf_id:
            logger.error("❌ 未选择场次，无法查询余票")
            return []
            
        logger.info(f"🔍 查询余票: PerfId={self.perf_id}")
        
        # TODO: 填入文档中的余票查询接口 URL
        url = f"{self.BASE_URL}/seat/availability"
        
        params = {
            "perfId": self.perf_id,
            "prodId": self.prod_id
        }
        
        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            # TODO: 解析余票数据
            # 假设返回结构: areas -> [{areaId, areaName, seatCount, price}]
            areas = data["data"]["areas"]
            
            # 过滤有票的区域
            available_areas = [a for a in areas if a["seatCount"] > 0]
            
            if available_areas:
                logger.info(f"✅ 发现 {len(available_areas)} 个可售区域")
                # 策略：选择第一个有票区域，或指定价格档位
                target_area = available_areas[0]
                self.ticket_area_id = target_area["areaId"]
                logger.info(f"🎯 锁定区域: {target_area['areaName']} (ID: {self.ticket_area_id})")
                return available_areas
            else:
                logger.warning("⚠️ 当前场次无余票")
                return []
                
        except Exception as e:
            logger.error(f"💥 查询余票失败: {e}")
            return []

    # ================= 步骤 4: 锁定座位 (选座) =================
    def select_seats(self, seat_ids: Optional[List[str]] = None) -> bool:
        """
        锁定座位。如果是选座席，传入 seat_ids；如果是配席，由服务器分配。
        """
        if not self.ticket_area_id:
            logger.error("❌ 未选择区域，无法锁座")
            return False
            
        logger.info("🪑 正在锁定座位...")
        
        # TODO: 填入文档中的锁座接口 URL
        url = f"{self.BASE_URL}/order/lock"
        
        payload = {
            "perfId": self.perf_id,
            "areaId": self.ticket_area_id,
            "count": 1, # 购买张数
            # 如果是选座席，需要具体座位号
            # "seatIds": seat_ids 
        }
        
        try:
            resp = self.session.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # TODO: 检查锁座结果
            if data.get("success"):
                self.ticket_seat_info = data["data"] # 保存 lockId 或 seatInfo
                logger.info("✅ 座位锁定成功！")
                return True
            else:
                logger.warning(f"⚠️ 锁座失败: {data.get('message')}")
                return False
                
        except Exception as e:
            logger.error(f"💥 锁座请求异常: {e}")
            return False

    # ================= 步骤 5: 生成订单 (下单前最后一步) =================
    def create_order_draft(self) -> Optional[str]:
        """
        创建订单草稿，获取 orderId，准备进入支付环节
        """
        if not self.ticket_seat_info:
            logger.error("❌ 未锁定座位，无法创建订单")
            return None
            
        logger.info("📝 正在生成订单...")
        
        # TODO: 填入文档中的创建订单接口 URL
        url = f"{self.BASE_URL}/order/create"
        
        payload = {
            "lockId": self.ticket_seat_info.get("lockId"), # 使用上一步的 lockId
            "prodId": self.prod_id,
            "perfId": self.perf_id,
            "buyerId": self.user_id,
            # 可能需要观众信息
            # "audiences": [{"name": "...", "phone": "..."}]
        }
        
        try:
            resp = self.session.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # TODO: 提取 OrderId
            if data.get("success"):
                order_id = data["data"]["orderId"]
                logger.info(f"🎉 订单创建成功！OrderId: {order_id}")
                logger.info("🚀 下一步：请跳转至支付页面完成付款。")
                return order_id
            else:
                logger.error(f"❌ 订单创建失败: {data.get('message')}")
                return None
                
        except Exception as e:
            logger.error(f"💥 创建订单异常: {e}")
            return None

    # ================= 主流程控制 =================
    def run_booking_flow(self, username, password, prod_id):
        """串联所有步骤"""
        # 1. 登录
        if not self.login(username, password):
            return
        
        # 2. 获取场次
        if not self.get_performance_details(prod_id):
            return
            
        # 3. 循环查票 (开售前可能需要轮询)
        max_retries = 50
        for i in range(max_retries):
            areas = self.check_ticket_availability()
            if areas:
                break
            logger.info(f"⏳ 第 {i+1} 次查票，暂无余票，等待中...")
            time.sleep(0.5) # 快速轮询
            
        if not areas:
            logger.error("❌ 超过最大重试次数，仍未找到余票")
            return

        # 4. 锁座
        if not self.select_seats():
            # 锁座失败通常意味着票被抢了，可能需要退回步骤 3 重新查
            logger.warning("⚠️ 锁座失败，尝试重新查票...")
            # 这里可以加一个简单的重试逻辑
            
        # 5. 下单
        order_id = self.create_order_draft()
        
        if order_id:
            print(f"\n✅ 恭喜！订单已生成：{order_id}")
            print("👉 请尽快在 App 或网页端完成支付！")
        else:
            print("\n❌ 未能成功下单。")

# 使用示例
if __name__ == "__main__":
    client = MelonTicketClient()
    
    # 配置信息
    USER = "laoguanguan"
    PASS = "guanhr2728836"
    PROD_ID = "212838" # 替换为真实的演出 ID
    
    client.run_booking_flow(USER, PASS, PROD_ID)