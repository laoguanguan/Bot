import requests
import time
import hashlib
import json
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MelonTicketClient:
    def __init__(self):
        self.session = requests.Session()
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
        self.BASE_URL = "https://ticket.melon.com/api/v1" # 示例，需替换为文档中的真实 Base URL

    # ================= 步骤 1: 登录与认证 =================
    def login(self, username: str, password: str, otp_code: Optional[str] = None) -> bool:
        """
        用户登录，获取 Auth Token
        """
        logger.info("? 正在执行登录...")
        
        # TODO: 填入文档中的登录接口 URL
        url = f"{self.BASE_URL}/auth/login" 
        
        payload = {
            "userId": username,
            "password": password,
            # 如果有 OTP，加入 payload
            # "otp": otp_code 
        }
        
        # 某些平台需要加密密码，例如 SHA256
        # payload["password"] = hashlib.sha256(password.encode()).hexdigest()

        try:
            resp = self.session.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # TODO: 根据文档解析响应，提取 Token
            if data.get("success") or data.get("code") == 200:
                self.auth_token = data["data"]["accessToken"] # 示例路径
                self.user_id = data["data"]["userId"]
                self.session.headers.update({"Authorization": f"Bearer {self.auth_token}"})
                logger.success("? 登录成功，Token 已保存")
                return True
            else:
                logger.error(f"? 登录失败: {data.get('message')}")
                return False
        except Exception as e:
            logger.error(f"? 登录请求异常: {e}")
            return False

    # ================= 步骤 2: 获取演出详情与场次 =================
    def get_performance_details(self, prod_id: str) -> Dict:
        """
        获取演出详情，包含所有场次 (PerfId) 列表
        """
        self.prod_id = prod_id
        logger.info(f"? 获取演出详情: {prod_id}")
        
        # TODO: 填入文档中的演出详情接口 URL
        url = f"{self.BASE_URL}/performance/detail"
        
        params = {
            "prodId": prod_id
        }
        
        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            # TODO: 解析场次列表
            # 假设返回结构中有 performanceList -> [{perfId, date, time, status}]
            performances = data["data"]["performanceList"] 
            
            # 筛选可购买的场次 (status == 'ON_SALE' 或类似)
            available_perfs = [p for p in performances if p["status"] == "ON_SALE"]
            
            if not available_perfs:
                logger.warning("?? 暂无可售场次")
                return {}
            
            # 策略：选择第一个可用场次，或根据时间筛选
            target_perf = available_perfs[0] 
            self.perf_id = target_perf["perfId"]
            self.place_id = target_perf.get("placeId")
            
            logger.info(f"? 选定场次: PerfId={self.perf_id}, 时间={target_perf.get('date')}")
            return target_perf
            
        except Exception as e:
            logger.error(f"? 获取演出详情失败: {e}")
            return {}

    # ================= 步骤 3: 查询余票与区域 (Seat Map) =================
    def check_ticket_availability(self) -> List[Dict]:
        """
        查询当前场次的余票情况，获取可买的区域 (Area)
        """
        if not self.perf_id:
            logger.error("? 未选择场次，无法查询余票")
            return []
            
        logger.info(f"? 查询余票: PerfId={self.perf_id}")
        
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
                logger.info(f"? 发现 {len(available_areas)} 个可售区域")
                # 策略：选择第一个有票区域，或指定价格档位
                target_area = available_areas[0]
                self.ticket_area_id = target_area["areaId"]
                logger.info(f"? 锁定区域: {target_area['areaName']} (ID: {self.ticket_area_id})")
                return available_areas
            else:
                logger.warning("?? 当前场次无余票")
                return []
                
        except Exception as e:
            logger.error(f"? 查询余票失败: {e}")
            return []

    # ================= 步骤 4: 锁定座位 (选座) =================
    def select_seats(self, seat_ids: Optional[List[str]] = None) -> bool:
        """
        锁定座位。如果是选座席，传入 seat_ids；如果是配席，由服务器分配。
        """
        if not self.ticket_area_id:
            logger.error("? 未选择区域，无法锁座")
            return False
            
        logger.info("? 正在锁定座位...")
        
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
                logger.success("? 座位锁定成功！")
                return True
            else:
                logger.warning(f"?? 锁座失败: {data.get('message')}")
                return False
                
        except Exception as e:
            logger.error(f"? 锁座请求异常: {e}")
            return False

    # ================= 步骤 5: 生成订单 (下单前最后一步) =================
    def create_order_draft(self) -> Optional[str]:
        """
        创建订单草稿，获取 orderId，准备进入支付环节
        """
        if not self.ticket_seat_info:
            logger.error("? 未锁定座位，无法创建订单")
            return None
            
        logger.info("? 正在生成订单...")
        
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
                logger.success(f"? 订单创建成功！OrderId: {order_id}")
                logger.info("? 下一步：请跳转至支付页面完成付款。")
                return order_id
            else:
                logger.error(f"? 订单创建失败: {data.get('message')}")
                return None
                
        except Exception as e:
            logger.error(f"? 创建订单异常: {e}")
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
            logger.info(f"? 第 {i+1} 次查票，暂无余票，等待中...")
            time.sleep(0.5) # 快速轮询
            
        if not areas:
            logger.error("? 超过最大重试次数，仍未找到余票")
            return

        # 4. 锁座
        if not self.select_seats():
            # 锁座失败通常意味着票被抢了，可能需要退回步骤 3 重新查
            logger.warning("?? 锁座失败，尝试重新查票...")
            # 这里可以加一个简单的重试逻辑
            
        # 5. 下单
        order_id = self.create_order_draft()
        
        if order_id:
            print(f"\n? 恭喜！订单已生成：{order_id}")
            print("? 请尽快在 App 或网页端完成支付！")
        else:
            print("\n? 未能成功下单。")

# 使用示例
if __name__ == "__main__":
    client = MelonTicketClient()
    
    # 配置信息
    USER = "your_melon_id"
    PASS = "your_password"
    PROD_ID = "100000" # 替换为真实的演出 ID
    
    client.run_booking_flow(USER, PASS, PROD_ID)