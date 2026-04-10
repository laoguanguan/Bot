# import requests
import time
import os
import hashlib
import re, json
import logging
from collections import defaultdict
from typing import Optional, Dict, List, Any
from datetime import datetime
from curl_cffi import requests
from playwright.sync_api import sync_playwright

COOKIE_FILE = "melon_cookies.json"

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_melon_timestamp() -> str:
    now = datetime.now()
    # 格式：年月日时分秒 + 毫秒（三位）
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"

# 解析 jsonp 响应
def parse_jsonp(schedule_header: str, response_text: str) -> dict | None:
    """
    解析 JSONP 响应，提取并返回内部 JSON 数据
    """
    try:
        # 使用正则匹配 scheduleList2(...) 中的内容
        # re.DOTALL 让 . 能匹配换行符（因为 JSON 可能多行）
        pattern = rf'{re.escape(schedule_header)}\((.*)\)'
        match = re.search(pattern, response_text, re.DOTALL)
        
        if not match:
            print("❌ 未找到 scheduleList(...) 结构")
            return None
            
        json_str = match.group(1).strip()  # 去除首尾空白
        
        # 解析 JSON
        data = json.loads(json_str)
        return data
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解码失败: {e}")
        print(f"提取出的字符串: {json_str[:200]}...")
        return None
    except Exception as e:
        print(f"💥 解析出错: {e}")
        return None

class MelonTicketClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.impersonate = "chrome120"
        # 设置通用 Headers (模拟浏览器)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh,ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://ticket.melon.com/",
            "Origin": "https://ticket.melon.com"
        }
        self.session.headers.update(self.headers)
        
        # 关键状态变量
        self.auth_token = None
        self.user_id = None
        self.prod_id = None       # 演出 ID
        self.place_id = None      # 场馆 ID
        self.perf_id = None       # 场次 ID 
        self.perfDay = None       # 演出时间
        
        # 座位信息
        self.area_floorNo = None # 楼层
        self.area_floorName = None # 楼层名称
        self.area_areaNo = None    # 区域
        
        self.seat_gradeNo = None # 座位等级
        self.seat_gradeName = None # 座位等级名称
        
        self.seat_block_id = None # 区域 ID
        self.seat_id = None # 选座信息
        
        # 验证码 token（由外部填入，或通过 Playwright/验证码服务获取）
        self.chkcapt = None
        # 购票限量
        self.limitVolume = "1"
        # 订单相关
        self.priceNo = None
        self.basePrice = None
        self.delvyTypeCode = "DV0002"  # 默认：现场领取
        self.cardCode = "FOREIGN_VISA"
        self.cardCodeName = "VISA"
        self.cardQuota = "12"           # 分期期数
        
        # TODO: 根据文档填入基础 URL
        self.BASE_URL = "https://tkglobal.melon.com" # 示例，需替换为文档中的真实 Base URL

    def _save_cookies(self):
        """将当前 Session 的 Cookie 保存到本地文件"""
        cookies = self.session.cookies.get_dict()
        logger.debug(f"💾 准备保存的完整 Cookie: {cookies}")  # ← 加这行！
        # for cookie in self.session.cookies:
        #     # 打印看看每个 cookie 的 domain 属性
        #     print(f"Cookie: {cookie.name}, Domain: {cookie.domain}")
        # pcid = self.session.cookies.get("PCID")
        # pc_pcid = self.session.cookies.get("PC_PCID")
        # fwb = self.session.cookies.get("_fwb")

        # 4. 打印结果
        # print("PCID:", pcid)
        # print("PC_PCID:", pc_pcid)
        # print("_fwb:", fwb)
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

    def get_all_cookies_verbose(self, session):
        """
        暴力提取 session 中所有可能的 cookie，忽略 domain/path 过滤
        """
        cookies_list = []
        
        # curl_cffi 的 cookies 属性通常是一个 http.cookiejar.CookieJar 对象
        # if hasattr(session, 'cookies') and session.cookies:
        #     for cookie in session.cookies:
        #         # 直接拼接 name=value
        #         cookies_list.append(f"{cookie.name}={cookie.value}")
        
        # return ''; '.join(cookies_list)'
        return ''
    
    def is_logged_in(self) -> bool:
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
    
    # 演出的详细信息接口
    def get_performance_detail_info(self, prodId, scheduleNo) -> Dict:
        perform_infoProSch_url = "https://tkglobal.melon.com/tktapi/product/informProdSch.json?v=1"
        perform_infoProSch_params = {
            "prodId"       : prodId,
            "pocCode"      : "SC0002",
            "scheduleNo"   : scheduleNo,
            "sellTypeCode" : "ST0001"
        }
        
        try:
            resp = self.session.post(perform_infoProSch_url, params=perform_infoProSch_params)
            if resp.status_code == 200 :
                infoProSch = resp.json() # "limitVolume" 代表每个人的限购数量
                return infoProSch
            else:
                return None
        except Exception as e: 
            print(f"💥 获取详细信息出错: {e}")
            return None
    
    def get_block_grade_seat_count(self) -> str:
        try:
            sntvList : str = ""
            resp = self.session.post(
                url="https://tkglobal.melon.com/tktapi/glb/product/summary.json",
                params={
                    "v":"1",
                    "callback": "getBlockGradeSeatCountCallBack",
                    "prodId": self.prod_id,
                    "pocCode": "SC0002",
                    "scheduleNo": self.scheduleNo,
                    "perfDate": self.perfDay,
                    "langCd": "EN"
                }
            )
            if resp.status_code == 200 : 
                resp.raise_for_status()
                summary_info = parse_jsonp("getBlockGradeSeatCountCallBack", resp.text) 
                ret_code = summary_info.get("code")
                if ret_code != '0000':
                    print(f"⚠️ 获取座位信息,接口返回 code: {ret_code}, message: {summary_info.get('message')}")
                else: 
                    for gradeinfo in summary_info["summary"]:
                        sntvList += gradeinfo["sntvList"]
                return sntvList
        except Exception as e:
            print(f"💥 get_block_grade_seat_count: {e}")
            return None
    
    def get_area_map_info(self) -> Dict:
        try:
            # 获取有空余座位的区块
            area_resp = self.session.post(
                url="https://tkglobal.melon.com/tktapi/glb/product/getAreaMap.json",
                params={
                    "v": 1,
                    "callback": "getBlockGradeSeatMapCallBack",
                    "prodId": self.prod_id,
                    "scheduleNo": self.scheduleNo,
                    "pocCode": "SC0002"
                },
                headers=self.cookie_headers
            )
            if area_resp.status_code == 200:
                area_resp.raise_for_status()
                area_resp_data = parse_jsonp("getBlockGradeSeatMapCallBack", area_resp.text)
                code = area_resp_data.get("code")
                if code != "0000":
                    print(f"⚠️ 获取座位区块信息失败,接口返回 code: {code}")
                    return []
                return area_resp_data
                area_da_sb_list = area_resp_data["seatData"]["da"]["sb"]
                return area_da_sb_list
            else:
                logger.error(f"❌ [get_area_map_info]: 无法查询到演出的销售状态, 状态码: {area_resp.status_code}")
                return None
            
        except Exception as e:
            print(f"💥 get_area_map_info: {e}")
            return None    
    
    def get_block_summary_count(self) -> Dict:
        try:            
            blockSeatDict: Dict = defaultdict(dict)
            resp = self.session.post(
                url="https://tkglobal.melon.com/tktapi/product/block/summary.json",
                params={
                    "v": 1,
                    "callback": "getBlockSummaryCountCallBack",
                    "prodId": self.prod_id,
                    "pocCode": "SC0002",
                    "scheduleNo": self.scheduleNo,
                    "seatGradeNo": "",
                },
                headers=self.cookie_headers
            )
            if resp.status_code == 200 :
                resp.raise_for_status()
                area_summary_data = parse_jsonp("getBlockSummaryCountCallBack", resp.text)
                code = area_summary_data.get("code")
                if code != "0000":
                    print(f"⚠️ 获取座位区块信息失败,接口返回 code: {code}")
                    return None
                area_summary = area_summary_data.get("summary", {})
                for area in area_summary:
                    area_floorNo = area["floorNo"]
                    area_areaName = area["areaName"]
                    blockSeatDict[area_floorNo][area_areaName]=area
                return area_summary
            else:
                print(f"❌ 无法查询到演出的销售状态")
                return [] 
        except Exception as e:
            print(f"💥 获取演出销售信息出错: {e}")
            return None 
    
    # 获取 MemberKey 和 UserId 的接口
    def get_member_key_info(self) -> int:
        """
        获取用户的 MemberKey 和 UserId
        这是登录后的第一步，后续接口调用都需要这个 UserId
        """
        url = "https://tkglobal.melon.com/member/getMemberKey.json"
        try:
            resp = self.session.post(url)
            if resp.status_code == 200 :
                # 尝试将响应解析为 JSON
                json_data = resp.json()
                # 关键判断
                member_key = json_data.get("memberKey")
                logger.info(f"✅ 获取 MemberKey 成功: {member_key}")
        except Exception as e:
            logger.error(f"💥 获取 MemberKey 请求异常: {e}")  
            return None      
        return member_key
    
    # buybuttonclick 接口，获取购票按钮点击后的关键信息（如订单草稿信息等）
    def _get_buy_button_click_info(self) -> str:
        buy_button_click_url = "https://tkglobal.melon.com/public/buyBtnClick.html"
        buy_button_click_params = {
            "pocID": "WP19",
            "prodId": self.prod_id,
            "memberKey": self.member_key,
        }
        
        buy_button_click_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json;",
            "Referer": "https://tkglobal.melon.com/performance/index.htm?langCd=EN&prodId="+self.prod_id
        }
        try:
            resp = self.session.get(buy_button_click_url, params=buy_button_click_params, headers=buy_button_click_headers)
            if resp.status_code == 200 :
                buy_html = resp.text
                logger.info(f"✅ 获取 buybuttonclick 信息成功")
                return buy_html
            else:
                logger.warning(f"⚠️ 获取购票按钮信息失败, 状态码: {resp.status_code}")
                return {}
        except Exception as e:
            logger.error(f"💥 获取 buyclick 请求异常: {e}")  
            return None      

    # ================= 打开预订弹窗 (onestop) =================
    def open_reservation_page(self) -> bool:
        """
        打开选座预订弹窗页面，执行以下步骤：
        1. POST onestop.htm 获取验证码图片
        2. 调用 getMemberKey.json
        3. 调用 checkCaptchaComplete.json 验证验证码
        4. 调用 informLimit.json 获取购票限量
        注意：self.chkcapt 必须在调用前设置（可通过 Playwright 或验证码服务获取）
        """
        logger.info("🎫 打开预订弹窗页面...")
        onestop_url = "https://tkglobal.melon.com/reservation/popup/onestop.htm"
        onestop_payload = {
            "prodId": self.prod_id,
            "pocCode": "SC0002",
            "scheduleNo": self.scheduleNo,
            "sellCondNo": "",
            "sellTypeCode": "ST0001",
            "t": "",
            "tYn": "N",
            "chk": "",
            "langCd": "EN",
            "netfunnel_key": "",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"https://tkglobal.melon.com/performance/index.htm?langCd=EN&prodId={self.prod_id}",
        }
        try:
            resp = self.session.post(onestop_url, data=onestop_payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"❌ 打开预订弹窗失败, 状态码: {resp.status_code}")
                return False
            # 从页面提取 captchaEncStr（备用，实际 chkcapt 需用户/服务解题后设置）
            import re as _re
            m = _re.search(r'id="captchaEncStr"\s+value="([^"]+)"', resp.text)
            if m:
                self.captchaEncStr = m.group(1)
                logger.info(f"📸 获取到验证码挑战串: {self.captchaEncStr}")
            else:
                self.captchaEncStr = None
                logger.warning("⚠️ 未找到 captchaEncStr，跳过")
        except Exception as e:
            logger.error(f"💥 打开预订弹窗异常: {e}")
            return False

        # 1. getMemberKey
        self.member_key = self.get_member_key_info()
        if not self.member_key:
            logger.error("❌ 获取 MemberKey 失败")
            return False

        # 2. checkCaptchaComplete（需要 chkcapt 已被设置）
        if not self.chkcapt:
            logger.warning("⚠️ chkcapt 未设置，跳过验证码验证（可能导致后续请求失败）")
        else:
            try:
                capt_resp = self.session.post(
                    "https://tkglobal.melon.com/reservation/ajax/checkCaptchaComplete.json",
                    data={"chkcapt": self.chkcapt, "prodId": self.prod_id},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                capt_data = capt_resp.json()
                if capt_data.get("CODE") != "0000":
                    logger.warning(f"⚠️ 验证码验证失败: {capt_data}")
                else:
                    logger.info("✅ 验证码验证通过")
            except Exception as e:
                logger.error(f"💥 验证码验证异常: {e}")

        # 3. informLimit（获取购票限量）
        try:
            limit_resp = self.session.post(
                "https://tkglobal.melon.com/tktapi/glb/product/informLimit.json",
                data={
                    "v": "1",
                    "prodId": self.prod_id,
                    "pocCode": "SC0002",
                    "scheduleNo": self.scheduleNo,
                    "sellTypeCode": "ST0001",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            limit_data = limit_resp.json()
            if limit_data.get("code") == "0000":
                self.limitVolume = limit_data.get("limitVolume", "1")
                logger.info(f"✅ 每人限购数量: {self.limitVolume}")
            else:
                logger.warning(f"⚠️ 获取限购数量失败: {limit_data}")
        except Exception as e:
            logger.error(f"💥 获取限购数量异常: {e}")

        return True

    def get_prod_sell_state(self) -> bool:
        """
        验证演出场次当前是否可购买（在选座循环中调用）
        """
        try:
            resp = self.session.post(
                "https://tkglobal.melon.com/tktapi_poc/performance/getProdSellState.json",
                params={"v": "1", "callback": "getValiProductScheduleCallBack"},
                data={"prodId": self.prod_id, "scheduleNo": self.scheduleNo},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                sell_state = parse_jsonp("getValiProductScheduleCallBack", resp.text)
                if sell_state and sell_state.get("result") == 0:
                    logger.info("✅ 演出场次状态正常，可购买")
                    return True
                else:
                    logger.warning(f"⚠️ 演出场次状态异常: {sell_state}")
                    return False
            else:
                logger.error(f"❌ getProdSellState 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 getProdSellState 异常: {e}")
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
            if self.is_logged_in():
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
                if self.is_logged_in():
                    logger.info("✅ 账号密码登录成功！")
                    # 4. 登录成功后，立即保存 Cookie
                    self._save_cookies()
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
        
    # ================= 使用playwright进行登录，模拟 =================
    # def login_by_playwright(self, username: str, password: str, otp_code: Optional[str] = None) -> bool:
    # ================= 步骤 2: 获取演出详情与场次 =================
    def get_performance_details(self, prod_id: str) -> int:
        
        self.prod_id = prod_id
        logger.info(f"🎭 获取演出详情: {prod_id}")
        
        # 填入文档中的演出详情接口 URL
        get_daylist_url = "https://tkglobal.melon.com/tktapi/glb/product/schedule/daylist.json"
        daylist_params = {
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
            # 解析场次列表, 确定表演日期 prefDay
            datalist_resp = self.session.get(get_daylist_url, params=daylist_params)
            datalist_resp.raise_for_status()
            datalist = parse_jsonp("scheduleList2", datalist_resp.text)
            
            datalistInfo = datalist.get("data")
            # prefDay 在后续传参中需要使用
            prefDay = datalistInfo["perfDaylist"][0]["perfDay"] # @todo 这里默认选择第一个日期，实际使用中可能需要根据用户输入选择
            self.preDayList = datalistInfo["perfDaylist"]
            self.perfDay = prefDay
            # ★ 场次编号，后续所有流程都需要
            get_timelist_url = "https://tkglobal.melon.com/tktapi/glb/product/schedule/timelist.json"
            timelist_params = {
                "callback": "scheduleList3",
                "v": 1,
                "prodId": prod_id,
                "perfDay": prefDay,
                "pocCode": "SC0002",
                "perfTypeCode": "GN0001",
                "sellTypeCode": "ST0001",
                "seatCntDisplayYn": "N",
                "langCd": "EN"
            }
            timelist_resp = self.session.get(get_timelist_url, params=timelist_params)
            timelist_resp.raise_for_status()
            timelist = parse_jsonp("scheduleList3", timelist_resp.text)
            
            timelistInfo = timelist.get("data")
            scheduleNo = timelistInfo["perfTimelist"][0]["scheduleNo"]
            self.scheduleNo = scheduleNo
            # 保存演出名称，后续 API 调用中需要用到
            self.perfMainName = datalistInfo.get("prodMainName", "")
            logger.info(f"✅ 获取演出详情成功！场次编号: {scheduleNo}, 演出名: {self.perfMainName}")
            return scheduleNo
            
        except Exception as e:
            logger.error(f"💥 获取演出详情失败: {e}")
            return {}

    # ================= 步骤 3: 查询余票与区域 (Seat Map) =================
    def check_ticket_availability(self) -> List[Dict]:
        """
        查询当前场次的余票情况，获取可买的区域 (Area)
        """
        if not self.prod_id:
            logger.error("❌ 未选择场次，无法查询余票")
            return []
            
        logger.info(f"🔍 查询余票: ProdId={self.prod_id}")
        
        # 填入查询座位等级列表, 获取有可用票
        get_gradelist_url = "https://tkglobal.melon.com/tktapi/glb/product/schedule/gradelist.json"
        gradelist_params = {
            "callback": "scheduleList4",
            "prodId": self.prod_id,
            "pocCode": "SC0002",
            "scheduleNo": self.scheduleNo,
            "perfTypeCode": "GN0001",
            "sellTypeCodeData": "ST0001",
            "langCd":"EN",
            "seatCntDisplayYn":"N",
            "v":1
        }
        
        try:
            # 查询余票
            gradelist_resp = self.session.get(get_gradelist_url, params=gradelist_params)
            gradelist_resp.raise_for_status()
            gradelist = parse_jsonp("scheduleList4", gradelist_resp.text)
            resultCode = gradelist.get("resultCode")
            
            if resultCode == "-1" :
                resultMessage = gradelist.get("resultMessage")
                logger.info("⚠️ 接口查询失败,返回报错提示 %s", resultMessage)
                return None # 无余票返回[]可继续下次轮询
            else :
                # 1.1 获取 MemberKey
                self.member_key = self.get_member_key_info() 
                self.button_html = self._get_buy_button_click_info()
                
                gradelistInfo = gradelist.get("data")
                self.realSetCntlk = gradelistInfo["seatGradelist"][0]["realSeatCntlk"]
                logger.info(f"✅ 余票数量: {self.realSetCntlk}")
                if (self.realSetCntlk == "0"):
                    logger.info("⚠️ 当前无余票，继续轮询...")
                    return [self.realSetCntlk] # 无余票返回0可继续下次轮询
                # 查询是否需要排队，获取排队KEY
                if self.realSetCntlk:
                    get_prodkey_url = "https://tkglobal.melon.com/tktapi/glb/product/prodKey.json"
                    get_prodkey_params = {
                        #"callback":"scheduleList8",
                        "prodId": self.prod_id,
                        "scheduleNo": self.scheduleNo,
                        "v":"1",
                        '_': str(int(time.time() * 1000))
                    }
                    # 测试发现使用网页的Cookie能有效,模仿浏览器却出现报错
                    cookie_dict = self.session.cookies.get_dict()
                    # full_cookie_str = self.get_all_cookies_verbose(self.session)
                    # full_cookie_str = 'PCID=17730672944097519966510; PC_PCID=17730672944097519966510; keyCookie_T=1018478961; NetFunnel_ID=WP15;'
                    self.cookie = 'PCID=17730672944097519966510; PC_PCID=17730672944097519966510; '
                    logger.info(f" 必要的 Cookie: {self.cookie}")
                    self.cookie_headers={'Cookie': self.cookie}
        
                    prodkey_resp = self.session.get(url=get_prodkey_url, params=get_prodkey_params, headers=self.cookie_headers)
                    prodkey_resp.raise_for_status()
                    if prodkey_resp.status_code != 200:
                        logger.warning(f"⚠️ 获取排队Key失败, 状态码: {prodkey_resp.status_code}, 返回内容: %s", prodkey_resp.text)
                        return [self.realSetCntlk] # 无法获取排队Key时，继续返回余票信息
                    prodkey_data = prodkey_resp.json()
                    logger.info(f"✅ 获取排队Key: %s", prodkey_data.get("key"))
                    
                    self.prodkey = prodkey_data["key"]   # 排密钥(加密)
                    self.nflActId = prodkey_data["nflActId"] # NetFunnel 活动ID
                    self.trafficCtrlYn = prodkey_data["trafficCtrlYn"] # Y=需要排队 N=不需要
                    if self.trafficCtrlYn == "Y":
                        # 进入排队
                        logger.info("⏳ 需要排队，正在进入排队...")
                    else:
                        # 不需要排队，直接返回余票信息
                        logger.info("🚀 不需要排队，直接返回余票信息")
                    
                return [self.realSetCntlk]
                
        except Exception as e:
            logger.error(f"💥 查询余票失败: {e}")
            return []
    
    # ================= 步骤 4: 锁定座位 (选座) =================
    def select_seats(self) -> bool:
        # 验证演出场次可购买状态
        self.get_prod_sell_state()
        sntv_list = self.get_block_grade_seat_count()
        area_resp_data = self.get_area_map_info()
        block_summary_info = self.get_block_summary_count()
        if not block_summary_info or not sntv_list or not area_resp_data:
            logger.error("⚠️ 无法获取座位区块信息，无法继续选座")
            return None
        area_da_sb_list = area_resp_data["seatData"]["da"]["sb"]
        
        # 进去后可能座位没了，加个循环
        try:
            has_check_seat_set = set()
            for area_da_sb in area_da_sb_list:
                # if area_da_sb["iv"] == "1": # iv判断不了区域是否有空位，还要研究
                #     seat_block_id = area_da_sb["sbid"]
                # 获取空余座位的座位ID[seatMapListJson]
                seat_block_id = 94 # @todo 测试时先写死一个区域，后续根据实际情况选择
                resp  = self.session.get(
                    url="https://tkglobal.melon.com/tktapi/product/seat/seatMapList.json", 
                    params={
                        "callback": "getSeatListCallBack",
                        "v": 1,
                        "prodId": self.prod_id,
                        "scheduleNo": self.scheduleNo,
                        "blockId": seat_block_id,
                        "pocCode": "SC0002",
                        "corpCodeNo":""
                    },
                    headers=self.cookie_headers
                    )

                if resp.status_code == 200 :
                    resp.raise_for_status()
                    area_map_data = parse_jsonp("getSeatListCallBack", resp.text)
                    seatData = area_map_data.get("seatData", {})
                    seatList = seatData["st"][0]["ss"]
                    floor = seatData['da']['sb'][0]['sntv']['f']
                    area = seatData['da']['sb'][0]['sntv']['a']
                    sntv = f"{floor},{area}"
                    block = None
                    for block_info in block_summary_info:
                        if block_info['floorNo'] == floor and block_info['areaNo'] == area:
                            block = block_info
                            self.area_floorName = block_info['floorName']
                            self.area_areaName = block_info['areaName']
                            break
                    for seat in seatList:
                        # @todo 查找未被锁定的座位，加速关键，当前的复杂度为o(n),需要优化
                        if seat["sid"] is None or seat["sid"] == "null": continue
                        if seat["sid"] in has_check_seat_set: continue
                        has_check_seat_set.add(seat["sid"])
                        self.seat_block_id = seat_block_id
                        self.seat_id = seat["sid"]
                        self.seat_row = seat["rn"]
                        self.seat_snm = seat["sn"]
                        self.seat_gradeNo = block["seatGradeNo"]
                        self.seat_gradeName = block["seatGradeName"]
                        self.sntv = sntv
                        self.area_areaNo = area
                        self.area_floorNo = floor
                        self.sntv_list = sntv_list
                        seat_snt = seatData['snt']
                        seatInfoList:str = ""
                        if seat_snt['f']['use'] == 'Y':    #楼层
                            seatInfoList += self.area_floorNo + ' ' + seat_snt['f']['name'] + ' '
                        if seat_snt['a']['use'] == 'Y':    #区域
                            seatInfoList += self.area_areaNo + ' ' + seat_snt['a']['name'] + ' '
                        if seat_snt['r']['use'] == 'Y':    #行
                            seatInfoList += str(self.seat_row) + ' ' + seat_snt['r']['name'] + ' '
                        if seat_snt['e']['use'] == 'Y':
                            seatInfoList += 'e' + ' ' + seat_snt['e']['name'] + ' '
                        if seat_snt['n']['use'] == 'Y':    #座位号
                            seatInfoList += self.seat_snm + ' ' + seat_snt['n']['name'] + ' '
                        self.seatinfoList = seatInfoList
                        logger.info(f"✅ 找到可用座位: {seatInfoList}，正在尝试锁定...")
                        break
                else:
                    logger.error(f"❌ [select_seats] 状态码: {resp.status_code}")
                    return None
                    
                if not self.seat_id or not self.seat_block_id:
                    logger.error("❌ 未选择区域，无法锁座")
                    return False
                
                logger.info(f"🪑 正在锁定座位: {self.seat_id}")
                # 座位锁定 (prodlimit) — 使用 POST body 发送参数（非 query params）
                callback_name = f"jQuery{int(time.time()*1000)}"
                prodlimit_payload = {
                    "langCd": "EN",
                    "prodId": self.prod_id,
                    "pocCode": "SC0002",
                    "perfTypeCode": "GN0001",
                    "perfDate": self.perfDay,
                    "scheduleNo": self.scheduleNo,
                    "sellTypeCode": "ST0001",
                    "sellCondNo": "",
                    "perfMainName": getattr(self, 'perfMainName', ""),
                    "seatGradeNo": "",
                    "seatGradeName": "",
                    "blockId": self.seat_block_id,
                    "sntv": self.sntv,
                    "blockTypeCode": "",
                    "floorNo": self.area_floorNo,
                    "floorName": self.area_floorName,
                    "areaNo": self.area_areaNo,
                    "areaName": self.area_areaName,
                    "prodTypeCode": "PT0001",
                    "flplanTypeCode": "DR0002",
                    "scheduleTypeCode": "SG0001",
                    "seatTypeCode": "SE0001",
                    "jType": "I",
                    "cardGroupId": "",
                    "cardBpId": "",
                    "cardMid": "",
                    "rsrvStep": "SAT",
                    "zamEnabled": "0",
                    "zamKey": "",
                    "trafficCtrlYn": "N",
                    "netfunnel_key": "",
                    "stvn_view_list": self.sntv_list,
                    "mapClickYn": "Y",
                    "seatId": self.seat_id,
                    "clipSeatId": "",
                    "chkcapt": self.chkcapt or "",
                }
                resp = self.session.post(
                    url="https://tkglobal.melon.com/tktapi/glb/reservation/prodlimit.json",
                    params={"v": 1, "callback": callback_name},
                    data=prodlimit_payload,
                    headers={**self.cookie_headers, "Content-Type": "application/x-www-form-urlencoded"},
                    )
                
                if resp.status_code != 200:
                    logger.error(f"❌ 锁座请求失败, 状态码: {resp.status_code}, 返回内容: {resp.text}")
                    return False
                
                resp.raise_for_status()
                prodlimit_result = parse_jsonp(callback_name, resp.text)
                
                if prodlimit_result.get("result") == "0000":
                    self.encryptedSeatIds = prodlimit_result["encryptedSeatIds"]
                    self.interlockTid = prodlimit_result.get("interlockTid", "0")
                    self.interlockTypeCode = prodlimit_result.get("interlockTypeCode", "")
                    logger.info("✅ 座位锁定成功！")
                    return True
                elif prodlimit_result.get("code") == 'T0002':
                    logger.warning(f"⚠️ 需要验证: {prodlimit_result.get('message')}")
                    return False
                else:
                    logger.warning(f"⚠️ 锁座失败: {prodlimit_result.get('message')}")
                
        except Exception as e:
            logger.error(f"💥 锁座请求异常: {e}")
            return False

    # ================= 步骤 5: 生成订单 =================
    def create_order_draft(self) -> Optional[Dict]:

        if not self.encryptedSeatIds:
            logger.error("❌ 没有锁定的座位信息，无法创建订单")
            return None

        # 5.1 提交选座 (stepTicket.htm)
        if not self.step_tick():
            logger.error("❌ 提交选座信息失败，无法创建订单")
            return None

        # 5.2 获取票种信息
        if not self.ticket_type():
            logger.error("❌ 获取票种信息失败")
            return None

        # 5.3 获取退票手续费（不阻断流程）
        self.get_cancel_fee()

        # 5.4 确认价格限制
        if not self.price_limit():
            logger.error("❌ 价格限制确认失败")
            return None

        # 5.5 获取配送步骤页面
        self.get_step_delvy()

        # 5.6 获取退票手续费（第二次，和 HAR 一致）
        self.get_cancel_fee()

        # 5.7 获取配送方式
        if not self.delivery_info():
            logger.error("❌ 获取配送信息失败")
            return None

        # 5.8 保存订单
        order_data = self.save_order()
        if not order_data:
            logger.error("❌ 保存订单失败")
            return None

        # 5.9 初始化支付
        self.pay_init_form()

        return order_data

    # ================= 主流程控制 =================
    def run_booking_flow(self, username, password, prod_id, proc_id):
        """串联所有步骤"""
        # 1. 登录
        if not self.login(username, password):
            return
        
        # 2. 获取场次
        if not self.get_performance_details(prod_id):
            return
            
        # 3. 循环查票 (开售前可能需要轮询)
        max_retries = 50
        areas = None
        for i in range(max_retries):
            areas = self.check_ticket_availability()
            if not areas:   # 接口报错，暂时跳出
                return
            if areas[0] == "0":  # 无余票，继续轮询
                logger.info(f"⏳ 第 {i+1} 次查票，暂无余票，等待中...")
                time.sleep(0.5)
                continue
            break
            
        if not areas or areas[0] == "0":
            logger.error("❌ 超过最大重试次数，仍未找到余票")
            return

        # 3.5 打开预订弹窗（getMemberKey + 验证码验证 + informLimit）
        # 注意：self.chkcapt 需要在此之前通过 Playwright 或验证码服务设置
        if not self.open_reservation_page():
            logger.error("❌ 打开预订弹窗失败")
            return

        # 4. 锁座
        if not self.select_seats():
            logger.warning("⚠️ 锁座失败，尝试重新查票...")
            return
            
        # 5. 下单
        order_data = self.create_order_draft()
        
        if order_data:
            print(f"\n✅ 恭喜！订单已生成！")
            print("👉 请尽快在 App 或网页端完成支付！")
        else:
            print("\n❌ 未能成功下单。")

    # 提交选座
    def step_tick(self) -> bool:
        url = "https://tkglobal.melon.com/reservation/popup/stepTicket.htm"
        payload = {
            'prodId': self.prod_id,
            'scheduleNo': self.scheduleNo,
            'flplanTypeCode': 'DR0002',
            'seatTypeCode': 'SE0001',
            'encryptedSeatIds': self.encryptedSeatIds,
            'interlockTypeCode': getattr(self, 'interlockTypeCode', ''),
            'interlockTid': getattr(self, 'interlockTid', '0'),
            'seatIds': self.seat_id,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://tkglobal.melon.com/reservation/popup/onestop.htm", 
            "User-Agent": self.headers["User-Agent"],
            "Cookie": self.cookie,
        }
        
        try:
            resp = self.session.post(url, data=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"❌ step_tick请求失败, 状态码: {resp.status_code}, 返回内容: {resp.text}")
            return True
        except Exception as e:
            logger.error(f"💥 提交选座请求异常: {e}")
            return False

    # 票种信息
    def ticket_type(self) -> bool:
        url = "https://tkglobal.melon.com/tktapi/glb/product/tickettype.json"
        callback_name = f"jQuery{int(time.time()*1000)}"
        payload = {
            "langCd": "EN",
            "prodId": self.prod_id,
            "pocCode": "SC0002",
            "perfTypeCode": "GN0001",
            "perfDate": self.perfDay,
            "scheduleNo": self.scheduleNo,
            "sellTypeCode": "ST0001",
            "sellCondNo": "",
            "perfMainName": getattr(self, 'perfMainName', ""),
            "seatGradeNo": "",
            "seatGradeName": "",
            "blockId": self.seat_block_id,
            "sntv": self.sntv,
            "blockTypeCode": "",
            "floorNo": self.area_floorNo,
            "floorName": self.area_floorName,
            "areaNo": self.area_areaNo,
            "areaName": self.area_areaName,
            "prodTypeCode": "PT0001",
            "flplanTypeCode": "DR0002",
            "scheduleTypeCode": "SG0001",
            "seatTypeCode": "SE0001",
            "jType": "I",
            "cardGroupId": "",
            "cardBpId": "",
            "cardMid": "",
            "rsrvStep": "SAT",
            "zamEnabled": "0",
            "trafficCtrlYn": "N",
            "stvn_view_list": self.sntv_list,
            "mapClickYn": "Y",
            "seatId": self.seat_id,
        }
        try:
            resp = self.session.post(url, params={"v": 1, "callback": callback_name}, data=payload,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
            if resp.status_code == 200:
                resp.raise_for_status()
                ticket_type_data = parse_jsonp(callback_name, resp.text)
                code = ticket_type_data.get("code")
                if code != "0000":
                    logger.warning(f"⚠️ 获取票种信息失败,接口返回 code: {code}, message: {ticket_type_data.get('message')}")
                    return False
                seatGradeList = ticket_type_data.get("seatGradeList", [])
                if not seatGradeList:
                    logger.warning("⚠️ seatGradeList 为空，无法获取票价信息")
                    return False
                grade = seatGradeList[0]
                prodTicketTypeList = grade.get("prodTicketTypeList", [])
                if prodTicketTypeList:
                    self.priceNo = prodTicketTypeList[0].get("priceNo", grade.get("priceNo", 0))
                    self.basePrice = prodTicketTypeList[0].get("basePrice", grade.get("basePrice", 0))
                else:
                    self.priceNo = grade.get("priceNo", 0)
                    self.basePrice = grade.get("basePrice", 0)
                logger.info(f"✅ 票种信息: priceNo={self.priceNo}, basePrice={self.basePrice}")
                return True
            else:
                logger.error(f"❌ 获取票种信息失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 获取票种信息异常: {e}")
            return False

    def get_cancel_fee(self) -> bool:
        """获取退票手续费信息"""
        try:
            callback_name = f"jQuery{int(time.time()*1000)}"
            resp = self.session.post(
                "https://tkglobal.melon.com/tktapi/glb/product/cancelfee.json",
                params={"v": 1, "callback": callback_name},
                data={"prodId": self.prod_id, "pocCode": "SC0002", "perfDate": self.perfDay},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                cancel_fee_data = parse_jsonp(callback_name, resp.text)
                logger.info(f"✅ 获取退票手续费信息成功")
                return True
            else:
                logger.warning(f"⚠️ 获取退票手续费信息失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 获取退票手续费异常: {e}")
            return False

    def price_limit(self) -> bool:
        """确认价格限制（tickettype 之后调用）"""
        try:
            callback_name = f"jQuery{int(time.time()*1000)}"
            payload = {
                "langCd": "EN",
                "prodId": self.prod_id,
                "pocCode": "SC0002",
                "perfTypeCode": "GN0001",
                "perfDate": self.perfDay,
                "scheduleNo": self.scheduleNo,
                "sellTypeCode": "ST0001",
                "sellCondNo": "",
                "perfMainName": getattr(self, 'perfMainName', ""),
                "seatGradeNo": "",
                "seatGradeName": "",
                "blockId": self.seat_block_id,
                "sntv": self.sntv,
                "blockTypeCode": "",
                "floorNo": self.area_floorNo,
                "floorName": self.area_floorName,
                "areaNo": self.area_areaNo,
                "areaName": self.area_areaName,
                "prodTypeCode": "PT0001",
                "flplanTypeCode": "DR0002",
                "scheduleTypeCode": "SG0001",
                "seatTypeCode": "SE0001",
                "jType": "I",
                "cardGroupId": "",
                "cardBpId": "",
                "cardMid": "",
                "rsrvStep": "SAT",
                "zamEnabled": "0",
                "zamKey": "",
                "trafficCtrlYn": "N",
                "netfunnel_key": "",
                "stvn_view_list": self.sntv_list,
                "mapClickYn": "Y",
                "priceNo": self.priceNo or 0,
                "rsrvVolume": "1",
                "chkcapt": self.chkcapt or "",
            }
            resp = self.session.post(
                "https://tkglobal.melon.com/tktapi/glb/reservation/pricelimit.json",
                params={"v": 1, "callback": callback_name},
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                pricelimit_data = parse_jsonp(callback_name, resp.text)
                if pricelimit_data.get("result") == "0000":
                    logger.info("✅ 价格限制确认成功")
                    return True
                else:
                    logger.warning(f"⚠️ 价格限制确认失败: {pricelimit_data.get('message')}")
                    return False
            else:
                logger.error(f"❌ pricelimit 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 price_limit 异常: {e}")
            return False

    def get_step_delvy(self) -> bool:
        """获取配送步骤页面（stepDelvy.htm）"""
        try:
            resp = self.session.get(
                "https://tkglobal.melon.com/reservation/popup/stepDelvy.htm",
                params={"prodId": self.prod_id, "scheduleNo": self.scheduleNo, "firstSeatId": self.seat_id},
                headers={"Referer": "https://tkglobal.melon.com/reservation/popup/onestop.htm"},
            )
            if resp.status_code == 200:
                logger.info("✅ 获取配送步骤页面成功")
                return True
            else:
                logger.warning(f"⚠️ 获取配送步骤页面失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 get_step_delvy 异常: {e}")
            return False

    def delivery_info(self) -> bool:
        url = "https://tkglobal.melon.com/tktapi/glb/product/delivery.json"
        callback_name = f"jQuery{int(time.time()*1000)}"
        payload = {
            "langCd": "EN",
            "prodId": self.prod_id,
            "pocCode": "SC0002",
            "perfTypeCode": "GN0001",
            "perfDate": self.perfDay,
            "scheduleNo": self.scheduleNo,
            "sellTypeCode": "ST0001",
            "sellCondNo": "",
            "perfMainName": getattr(self, 'perfMainName', ""),
            "seatGradeNo": "",
            "seatGradeName": "",
            "blockId": self.seat_block_id,
            "sntv": self.sntv,
            "blockTypeCode": "",
            "floorNo": self.area_floorNo,
            "floorName": self.area_floorName,
            "areaNo": self.area_areaNo,
            "areaName": self.area_areaName,
            "prodTypeCode": "PT0001",
            "flplanTypeCode": "DR0002",
            "scheduleTypeCode": "SG0001",
            "seatTypeCode": "SE0001",
            "jType": "I",
            "rsrvStep": "SAT",
            "zamEnabled": "0",
            "trafficCtrlYn": "N",
        }
        try:
            resp = self.session.post(url, params={"v": 1, "callback": callback_name}, data=payload,
                                     headers={**self.cookie_headers, "Content-Type": "application/x-www-form-urlencoded"})
            if resp.status_code == 200:
                resp.raise_for_status()
                delivery_info_data = parse_jsonp(callback_name, resp.text)
                code = delivery_info_data.get("code")
                if code != "0000":
                    logger.warning(f"⚠️ 获取配送信息失败,接口返回 code: {code}, message: {delivery_info_data.get('message')}")
                    return False
                # 保存配送信息供 save_order 使用
                self.delivery_data = delivery_info_data
                return True
            else:
                logger.error(f"❌ 获取配送信息失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 获取配送信息异常: {e}")
            return False

    def save_order(self) -> Optional[Dict]:
        import json as _json
        seat_info = [{
            'priceNo': self.priceNo,
            'seatId': self.seat_id,
            'gradeNm': self.seat_gradeName,
            'seatNm': self.seatinfoList,
            'basePrice': self.basePrice,
            'priceName': '기본가',
            'sejongPriceCode': None,
        }]
        url = "https://tkglobal.melon.com/tktapi/glb/reservation/save.json"
        # payAmt = basePrice + rsrvFee (5000 KRW), 若无法确定则使用 basePrice
        pay_amt = (self.basePrice or 0) + 5000
        payload = {
            'jType': 'I',
            'delvyTypeCode': self.delvyTypeCode,  # DV0002=现场领取
            'tel': getattr(self, 'phone', ''),
            'email': getattr(self, 'user_id', ''),
            'recv_country': '',
            'recv_name': '',
            'recv_address': '',
            'recv_city': '',
            'recv_state': '',
            'recv_zipno': '',
            'recv_tel1': '',
            'recv_tel2': '',
            'recv_country_code': '',
            'recv_delvy_price': '0',
            'addAddress': '',
            'payMethodCode': 'AP0012',
            'cardCode': self.cardCode,
            'cardCodeName': self.cardCodeName,
            'autheTypeCode': 'AT0005',
            'cardQuota': self.cardQuota,
            'quota': '00',
            'chkAgreeAll': 'on',
            'prodId': self.prod_id,
            'pocCode': 'SC0002',
            'scheduleNo': self.scheduleNo,
            'rsrvVolume': '1',
            'payAmt': pay_amt,
            'cardBpId': '',
            'cardMid': '',
            'priceNo': self.priceNo or 0,
            'seatId': self.seat_id,
            'advtkNo': '',
            'seatInfoListWithPriceType': _json.dumps(seat_info, ensure_ascii=False),
            'firstSeatId': self.seat_id,
            'sellTypeCode': 'ST0001',
            'chkcapt': self.chkcapt or '',
        }
        # chkAgree×6（协议同意）
        agree_list = [('chkAgree', 'on')] * 6
        
        try:
            # requests 不支持重复 key，改用列表拼接
            from urllib.parse import urlencode
            agree_encoded = urlencode(agree_list)
            body = urlencode(payload) + '&' + agree_encoded
            resp = self.session.post(url,
                params={"v": 1, "callback": "saveHandler"},
                data=body,
                headers={**self.cookie_headers, "Content-Type": "application/x-www-form-urlencoded"})
            if resp.status_code == 200:
                resp.raise_for_status()
                save_order_data = parse_jsonp("saveHandler", resp.text)
                code = save_order_data.get("code")
                if code != "0000":
                    logger.warning(f"⚠️ 保存订单失败,接口返回 code: {code}, message: {save_order_data.get('message')}")
                    return None
                logger.info("✅ 订单保存成功！")
                self.save_order_data = save_order_data
                return save_order_data
        except Exception as e:
            logger.error(f"💥 保存订单异常: {e}")
            return None

    def pay_init_form(self) -> bool:
        """初始化支付表单（最终触发支付流程）"""
        if not hasattr(self, 'save_order_data') or not self.save_order_data:
            logger.error("❌ 无订单数据，无法初始化支付")
            return False
        try:
            import json as _json
            data = self.save_order_data
            payload = {
                'flplanTypeCode': data.get('flplanTypeCode', 'DR0002'),
                'code': data.get('code', '0000'),
                'seatInfoListWithPriceType': data.get('seatInfoListWithPriceType', ''),
                'cardCode': data.get('cardCode', self.cardCode),
                'jtype': data.get('jtype', 'I'),
                'eType': data.get('eType', ''),
            }
            resp = self.session.post(
                "https://tkglobal.melon.com/reservation/ajax/payInitForm.htm",
                params={"procMode": "R"},
                data=payload,
                headers={**self.cookie_headers, "Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                logger.info("✅ 支付初始化成功！")
                # 响应可能包含跳转URL或支付表单
                logger.info(f"支付页面预览: {resp.text[:300]}")
                return True
            else:
                logger.error(f"❌ 支付初始化失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 pay_init_form 异常: {e}")
            return False
        
# 使用示例
if __name__ == "__main__":
    
    client = MelonTicketClient()
    
    # 配置信息
    TELL = "13682846798"
    USER = "790877095@qq.com"
    PASS = "guanhr2728836"
    # PROD_ID = "212838" # 替换为真实的演出 ID
    PROD_ID = "212638"
    PROC_ID = "WP19"
    client.proc_id = PROC_ID
    client.phone = TELL
    client.run_booking_flow(USER, PASS, PROD_ID, PROC_ID)