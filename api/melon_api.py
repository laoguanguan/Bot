# apis/melon_api.py

import time
import json
import requests
from typing import Dict, Any, Optional
from urllib.parse import urljoin

# Melon Ticket 基础 URL
BASE_URL = "https://ticket.melon.com"
API_BASE = "https://api-ticket.melon.com"

class MelonAPI:
    def __init__(self, session: requests.Session):
        """
        初始化 Melon API 客户端
        :param session: 已登录的 requests.Session 对象（含 cookies）
        """
        self.session = session
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": BASE_URL,
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
        })

    def get_concert_detail(self, concert_id: str) -> Optional[Dict[Any, Any]]:
        """
        获取演出详情（含场次、票价等）
        URL 示例: https://ticket.melon.com/performance/index.htm?prodId=20049032
        但数据通常来自 XHR 请求
        """
        # 实际接口可能需要从页面中提取，这里模拟一个常见 API 路径
        url = f"{API_BASE}/performance/v1/products/{concert_id}"
        try:
            resp = self.session.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[ERROR] 获取演出详情失败: {e}")
            return None

    def check_seat_availability(self, round_id: str) -> Optional[Dict[Any, Any]]:
        """
        查询某一场次的座位余票情况
        :param round_id: 场次 ID（通常在演出详情中获取）
        """
        url = f"{API_BASE}/reservation/v1/rounds/{round_id}/seats"
        try:
            resp = self.session.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[ERROR] 查询余票失败: {e}")
            return None

    def reserve_ticket(self, round_id: str, seat_ids: list) -> bool:
        """
        提交预约（预占座位）
        注意：Melon 通常分“预约”和“支付”两步
        """
        url = f"{API_BASE}/reservation/v1/reservations"
        payload = {
            "roundId": round_id,
            "seatIds": seat_ids,
            "requestTime": int(time.time() * 1000)
        }
        try:
            resp = self.session.post(url, data=json.dumps(payload))
            resp.raise_for_status()
            result = resp.json()
            if result.get("success"):
                print("[SUCCESS] 座位预约成功！")
                return True
            else:
                print(f"[FAIL] 预约失败: {result.get('message')}")
                return False
        except Exception as e:
            print(f"[ERROR] 预约请求异常: {e}")
            return False

    def get_reservation_status(self, reservation_id: str) -> Optional[Dict[Any, Any]]:
        """查询预约状态（用于确认是否仍有效）"""
        url = f"{API_BASE}/reservation/v1/reservations/{reservation_id}"
        try:
            resp = self.session.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[ERROR] 查询预约状态失败: {e}")
            return None

    def confirm_payment(self, reservation_id: str, payment_method: str = "CARD") -> bool:
        """
        确认支付（模拟，实际可能跳转到外部支付网关）
        注意：此步骤通常受严格风控，需处理 OTP、3D Secure 等
        """
        url = f"{API_BASE}/payment/v1/reservations/{reservation_id}/confirm"
        payload = {"paymentMethod": payment_method}
        try:
            resp = self.session.post(url, data=json.dumps(payload))
            resp.raise_for_status()
            result = resp.json()
            return result.get("success", False)
        except Exception as e:
            print(f"[ERROR] 支付确认失败: {e}")
            return False