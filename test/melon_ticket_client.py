# import requests
import time
import os
import re, json
import logging
from collections import defaultdict
from typing import Optional, Dict, List, Any
from datetime import datetime
from curl_cffi import requests

COOKIE_FILE = "melon_cookies.json"

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_melon_timestamp() -> str:
    now = datetime.now()
    # 格式：年月日时分秒 + 毫秒（三位）
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}"

# 解析 jsonp 响应
def parse_jsonp(callback_name: str, response_text: str) -> dict | None:
    """
    解析 JSONP 响应，提取并返回内部 JSON 数据
    支持 callback({...}) 和 /**/callback({...}); 两种格式
    """
    json_str = None
    try:
        # 使用正则匹配 callbackName(...) 中的内容，支持前缀 /**/ 和尾部 ;
        pattern = rf'(?:/\*\*/)?{re.escape(callback_name)}\((.*)\);?\s*$'
        match = re.search(pattern, response_text, re.DOTALL)
        
        if not match:
            print(f"❌ 未找到 {callback_name}(...) 结构")
            return None
            
        json_str = match.group(1).strip()
        data = json.loads(json_str)
        return data
        
    except json.JSONDecodeError as e:
        preview = json_str[:200] if json_str else response_text[:200]
        print(f"❌ JSON 解码失败: {e}, 内容预览: {preview}...")
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
        从 session 中提取 cookie 字符串（用于需要显式传递 Cookie 头的请求）
        """
        cookies = session.cookies.get_dict()
        return '; '.join(f'{k}={v}' for k, v in cookies.items())
    
    def _get_cookie_header(self) -> Dict:
        """返回包含当前 session cookie 的请求头"""
        cookie_str = self.get_all_cookies_verbose(self.session)
        return {'Cookie': cookie_str} if cookie_str else {}
    
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
        perform_infoProSch_url = "https://tkglobal.melon.com/tktapi/product/informProdSch.json"
        perform_infoProSch_data = {
            "prodId"       : prodId,
            "pocCode"      : "SC0002",
            "scheduleNo"   : scheduleNo,
            "sellTypeCode" : "ST0001",
            "sellCondNo"   : "",
            "perfDate"     : "",
        }
        
        try:
            resp = self.session.post(perform_infoProSch_url, params={"v": "1"}, data=perform_infoProSch_data)
            if resp.status_code == 200:
                infoProSch = resp.json()
                # 存储演出名称和手续费，后续接口需要
                prodInform = infoProSch.get("prodInform", {})
                self.perfMainName = prodInform.get("perfMainName", "")
                self.rsrvFee = prodInform.get("rsrvFee", 0)
                logger.info(f"✅ 演出信息: {self.perfMainName}, 手续费: {self.rsrvFee}")
                return infoProSch
            else:
                return None
        except Exception as e: 
            print(f"💥 获取详细信息出错: {e}")
            return None

    def enter_booking_page(self) -> bool:
        """
        进入购票弹窗页面（POST onestop.htm），携带排队获得的 chk 密钥
        必须在选座前调用，以建立有效的购票会话
        """
        url = "https://tkglobal.melon.com/reservation/popup/onestop.htm"
        data = {
            "prodId": self.prod_id,
            "pocCode": "SC0002",
            "scheduleNo": self.scheduleNo,
            "sellCondNo": "",
            "sellTypeCode": "ST0001",
            "t": "",
            "tYn": "N",
            "chk": getattr(self, "prodkey", ""),
            "langCd": "EN",
            "netfunnel_key": "",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"https://tkglobal.melon.com/performance/index.htm?langCd=EN&prodId={self.prod_id}",
        }
        try:
            resp = self.session.post(url, data=data, headers=headers)
            if resp.status_code == 200:
                logger.info("✅ 成功进入购票弹窗页面")
                return True
            else:
                logger.error(f"❌ 进入购票页面失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 进入购票页面异常: {e}")
            return False

    def check_captcha_complete(self, chkcapt: str) -> bool:
        """
        验证验证码完成状态（POST checkCaptchaComplete.json）
        chkcapt: 验证码加密令牌（从验证码图片接口或人工输入获取）
        """
        url = "https://tkglobal.melon.com/reservation/ajax/checkCaptchaComplete.json"
        data = {
            "chkcapt": chkcapt,
            "prodId": self.prod_id,
        }
        try:
            resp = self.session.post(url, data=data)
            if resp.status_code == 200:
                result = resp.json()
                if result.get("CODE") == "0000":
                    self.chkcapt = chkcapt
                    logger.info("✅ 验证码验证通过")
                    return True
                else:
                    logger.warning(f"⚠️ 验证码验证失败: {result}")
                    return False
            else:
                logger.error(f"❌ 验证码请求失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 验证码验证异常: {e}")
            return False

    def get_prod_sell_state(self) -> bool:
        """
        验证演出销售状态（POST getProdSellState.json）
        result=0 表示可售
        """
        url = "https://tkglobal.melon.com/tktapi_poc/performance/getProdSellState.json"
        data = {
            "prodId": self.prod_id,
            "scheduleNo": self.scheduleNo,
        }
        try:
            resp = self.session.post(url, params={"v": "1", "callback": "getValiProductScheduleCallBack"}, data=data)
            if resp.status_code == 200:
                result_data = parse_jsonp("getValiProductScheduleCallBack", resp.text)
                if result_data and result_data.get("result") == 0:
                    logger.info("✅ 演出销售状态正常")
                    return True
                else:
                    logger.warning(f"⚠️ 演出销售状态异常: {result_data}")
                    return False
            else:
                logger.error(f"❌ 查询销售状态失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 查询销售状态异常: {e}")
            return False
    
    def get_block_grade_seat_count(self) -> str:
        try:
            sntvList : str = ""
            resp = self.session.post(
                url="https://tkglobal.melon.com/tktapi/glb/product/summary.json",
                params={
                    "v": "1",
                    "callback": "getBlockGradeSeatCountCallBack",
                },
                data={
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
                    "v": "1",
                    "callback": "getBlockGradeSeatMapCallBack",
                },
                data={
                    "prodId": self.prod_id,
                    "scheduleNo": self.scheduleNo,
                    "pocCode": "SC0002"
                }
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
                    "v": "1",
                    "callback": "getBlockSummaryCountCallBack",
                },
                data={
                    "prodId": self.prod_id,
                    "pocCode": "SC0002",
                    "scheduleNo": self.scheduleNo,
                }
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
            logger.info(f"✅ 获取演出详情成功！场次编号: {scheduleNo}")
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
                        "prodId": self.prod_id,
                        "scheduleNo": self.scheduleNo,
                        "v": "1",
                        '_': str(int(time.time() * 1000))
                    }
        
                    prodkey_resp = self.session.get(url=get_prodkey_url, params=get_prodkey_params)
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
    
    def _build_seat_context_data(self) -> Dict:
        """
        构建选座相关接口共用的 POST 请求体参数
        （tickettype、pricelimit、delivery 等接口共享此参数集）
        """
        return {
            "langCd": "EN",
            "prodId": self.prod_id,
            "pocCode": "SC0002",
            "perfTypeCode": "GN0001",
            "perfDate": self.perfDay,
            "scheduleNo": self.scheduleNo,
            "sellTypeCode": "ST0001",
            "sellCondNo": "",
            "perfMainName": getattr(self, "perfMainName", ""),
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
            "stvn_view_list": self.sntv_list,
            "mapClickYn": "Y",
        }

    # ================= 步骤 4: 锁定座位 (选座) =================
    def select_seats(self) -> bool:
        sntv_list = self.get_block_grade_seat_count()
        area_resp_data = self.get_area_map_info()
        block_summary_info = self.get_block_summary_count()
        if not block_summary_info or not sntv_list or not area_resp_data:
            logger.error("⚠️ 无法获取座位区块信息，无法继续选座")
            return None
        area_da_sb_list = area_resp_data["seatData"]["da"]["sb"]

        try:
            has_check_seat_set = set()
            for area_da_sb in area_da_sb_list:
                # @todo 测试时先写死一个区域，后续根据实际情况选择
                seat_block_id = 94
                resp = self.session.get(
                    url="https://tkglobal.melon.com/tktapi/product/seat/seatMapList.json",
                    params={
                        "callback": "getSeatListCallBack",
                        "v": "1",
                        "prodId": self.prod_id,
                        "scheduleNo": self.scheduleNo,
                        "blockId": seat_block_id,
                        "pocCode": "SC0002",
                        "corpCodeNo": ""
                    })

                if resp.status_code == 200:
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
                        # @todo 查找未被锁定的座位，复杂度 O(n)，后续可优化
                        if seat["sid"] is None or seat["sid"] == "null": continue
                        if seat["sid"] in has_check_seat_set: continue
                        has_check_seat_set.add(seat["sid"])
                        self.seat_block_id = seat_block_id
                        self.seat_id = seat["sid"]
                        self.seat_row = seat["rn"]
                        self.seat_snm = seat["sn"]
                        self.seat_gradeNo = block["seatGradeNo"] if block else ""
                        self.seat_gradeName = block["seatGradeName"] if block else ""
                        self.sntv = sntv
                        self.area_areaNo = area
                        self.area_floorNo = floor
                        self.sntv_list = sntv_list
                        seat_snt = seatData['snt']
                        seatInfoList: str = ""
                        if seat_snt['f']['use'] == 'Y':    # 楼层
                            seatInfoList += self.area_floorNo + ' ' + seat_snt['f']['name'] + ' '
                        if seat_snt['a']['use'] == 'Y':    # 区域
                            seatInfoList += self.area_areaNo + ' ' + seat_snt['a']['name'] + ' '
                        if seat_snt['r']['use'] == 'Y':    # 行
                            seatInfoList += str(self.seat_row) + ' ' + seat_snt['r']['name'] + ' '
                        if seat_snt['e']['use'] == 'Y':
                            seatInfoList += 'e' + ' ' + seat_snt['e']['name'] + ' '
                        if seat_snt['n']['use'] == 'Y':    # 座位号
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

                if not getattr(self, "chkcapt", None):
                    logger.error("❌ 缺少 chkcapt 验证码令牌，请先调用 check_captcha_complete()")
                    return False

                # 座位锁定 (prodlimit): v/callback 在 URL，其余在 POST body
                prodlimit_body = {
                    "langCd": "EN",
                    "prodId": self.prod_id,
                    "pocCode": "SC0002",
                    "perfTypeCode": "GN0001",
                    "perfDate": self.perfDay,
                    "scheduleNo": self.scheduleNo,
                    "sellTypeCode": "ST0001",
                    "sellCondNo": "",
                    "perfMainName": getattr(self, "perfMainName", ""),
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
                    "stvn_view_list": self.sntv_list,
                    "mapClickYn": "Y",
                    "seatId": self.seat_id,
                    "chkcapt": self.chkcapt,
                }
                resp = self.session.post(
                    url="https://tkglobal.melon.com/tktapi/glb/reservation/prodlimit.json",
                    params={"v": "1", "callback": "jQuery360029390494093780284_1775304449633"},
                    data=prodlimit_body,
                )

                if resp.status_code != 200:
                    logger.error(f"❌ 锁座请求失败, 状态码: {resp.status_code}, 返回内容: {resp.text}")
                    return False

                resp.raise_for_status()
                prodlimit_data = parse_jsonp("jQuery360029390494093780284_1775304449633", resp.text)

                if prodlimit_data.get("result") == "0000":
                    self.encryptedSeatIds = prodlimit_data["encryptedSeatIds"]
                    self.interlockTid = prodlimit_data.get("interlockTid", "0")
                    self.interlockTypeCode = prodlimit_data.get("interlockTypeCode", "")
                    logger.info("✅ 座位锁定成功！")
                    return True
                elif prodlimit_data.get("code") == 'T0002':
                    logger.warning(f"⚠️ 需要验证: {prodlimit_data.get('message')}")
                    return False
                else:
                    logger.warning(f"⚠️ 锁座失败: {prodlimit_data.get('message')}")

        except Exception as e:
            logger.error(f"💥 锁座请求异常: {e}")
            return False

    # ================= 步骤 5: 生成订单 (下单前最后一步) =================
    def create_order_draft(self) -> Optional[str]:

        if not self.encryptedSeatIds:
            logger.error("❌ 没有锁定的座位信息，无法创建订单")
            return None

        if not self.step_tick():  # 提交选座信息
            logger.error("❌ 提交选座信息失败，无法创建订单")
            return None

        if not self.ticket_type():  # 获取票种和价格信息
            return None

        if not self.pricelimit():   # 价格限制检查
            return None

        # 获取配送页面（stepDelvy.htm GET）
        self._get_step_delvy()

        if not self.delivery_info():  # 配送方式
            return None

        return self.save_order()   # 保存订单，返回订单号

    # ================= 主流程控制 =================
    def run_booking_flow(self, username, password, prod_id, proc_id, chkcapt: str = None):
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
            if not areas:   # 接口异常，暂时跳出
                return
            if areas[0] != "0":  # 有余票
                break
            logger.info(f"⏳ 第 {i+1} 次查票，暂无余票，等待中...")
            time.sleep(0.5)

        if not areas or areas[0] == "0":
            logger.error("❌ 超过最大重试次数，仍未找到余票")
            return

        # 3.5 进入购票弹窗
        self.get_performance_detail_info(prod_id, self.scheduleNo)
        if not self.enter_booking_page():
            return

        # 验证码（如传入 chkcapt 则自动完成；否则需要人工介入）
        if chkcapt:
            if not self.check_captcha_complete(chkcapt):
                logger.error("❌ 验证码验证失败，中止流程")
                return
        else:
            logger.warning("⚠️ 未提供 chkcapt，跳过验证码步骤（锁座时可能失败）")

        # 4. 锁座
        if not self.select_seats():
            logger.warning("⚠️ 锁座失败，尝试重新查票...")
            return

        # 5. 下单
        order_id = self.create_order_draft()

        if order_id:
            print(f"\n✅ 恭喜！订单已生成：{order_id}")
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
        }

        try:
            resp = self.session.post(url, data=payload, headers=headers)
            if resp.status_code != 200:
                logger.error(f"❌ step_tick请求失败, 状态码: {resp.status_code}, 返回内容: {resp.text}")
                return False
            return True
        except Exception as e:
            logger.error(f"💥 提交选座请求异常: {e}")
            return False

    # 票种信息
    def ticket_type(self) -> bool:
        url = "https://tkglobal.melon.com/tktapi/glb/product/tickettype.json"
        seat_data = self._build_seat_context_data()
        seat_data["seatId"] = self.seat_id
        try:
            resp = self.session.post(
                url,
                params={"v": "1", "callback": "jQuery360036452094407238755_1775385067625"},
                data=seat_data,
            )
            if resp.status_code == 200:
                resp.raise_for_status()
                ticket_type_data = parse_jsonp("jQuery360036452094407238755_1775385067625", resp.text)
                code = ticket_type_data.get("code")
                if code != "0000":
                    logger.warning(f"⚠️ 获取票种信息失败,接口返回 code: {code}, message: {ticket_type_data.get('message')}")
                    return False
                seatGradeList = ticket_type_data.get("seatGradeList", [])
                if not seatGradeList:
                    logger.error("❌ seatGradeList 为空")
                    return False
                grade = seatGradeList[0]
                prod_ticket_types = grade.get("prodTicketTypeList", [])
                if not prod_ticket_types:
                    logger.error("❌ prodTicketTypeList 为空")
                    return False
                self.priceNo = prod_ticket_types[0]["priceNo"]
                self.basePrice = grade["basePrice"]
                logger.info(f"✅ 票种信息获取成功: priceNo={self.priceNo}, basePrice={self.basePrice}")
                return True
            else:
                logger.error(f"❌ 获取票种信息失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 获取票种信息异常: {e}")
            return False

    def pricelimit(self) -> bool:
        """价格限制检查"""
        url = "https://tkglobal.melon.com/tktapi/glb/reservation/pricelimit.json"
        seat_data = self._build_seat_context_data()
        seat_data["priceNo"] = getattr(self, "priceNo", "")
        seat_data["rsrvVolume"] = 1
        seat_data["chkcapt"] = getattr(self, "chkcapt", "")
        try:
            resp = self.session.post(
                url,
                params={"v": "1", "callback": "jQuery360013851413678480873_1775390381550"},
                data=seat_data,
            )
            if resp.status_code == 200:
                resp.raise_for_status()
                pricelimit_data = parse_jsonp("jQuery360013851413678480873_1775390381550", resp.text)
                result = pricelimit_data.get("result")
                if result != "0000":
                    logger.warning(f"⚠️ 价格限制检查失败, result: {result}, message: {pricelimit_data.get('message')}")
                    return False
                logger.info("✅ 价格限制检查通过")
                return True
            else:
                logger.error(f"❌ 价格限制检查失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 价格限制检查异常: {e}")
            return False

    def _get_step_delvy(self) -> None:
        """获取配送页面（GET stepDelvy.htm）"""
        url = "https://tkglobal.melon.com/reservation/popup/stepDelvy.htm"
        params = {
            "prodId": self.prod_id,
            "scheduleNo": self.scheduleNo,
            "firstSeatId": self.seat_id,
        }
        try:
            resp = self.session.get(url, params=params)
            logger.info(f"📄 stepDelvy.htm 状态码: {resp.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ _get_step_delvy 异常 (非阻断): {e}")

    def delivery_info(self) -> bool:
        url = "https://tkglobal.melon.com/tktapi/glb/product/delivery.json"
        seat_data = self._build_seat_context_data()
        try:
            resp = self.session.post(
                url,
                params={"v": "1", "callback": "jQuery36003375847762393991_1775390385778"},
                data=seat_data,
            )
            if resp.status_code == 200:
                resp.raise_for_status()
                delivery_info_data = parse_jsonp("jQuery36003375847762393991_1775390385778", resp.text)
                code = delivery_info_data.get("code")
                if code != "0000":
                    logger.warning(f"⚠️ 获取配送信息失败,接口返回 code: {code}, message: {delivery_info_data.get('message')}")
                    return False
                logger.info("✅ 配送信息获取成功")
                return True
            else:
                logger.error(f"❌ 获取配送信息失败, 状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"💥 获取配送信息异常: {e}")
            return False

    def save_order(self) -> Optional[str]:
        seat_info = {
            "priceNo": self.priceNo,
            "seatId": self.seat_id,
            "gradeNm": self.seat_gradeName,
            "seatNm": self.seatinfoList,
            "basePrice": self.basePrice,
        }
        url = "https://tkglobal.melon.com/tktapi/glb/reservation/save.json"
        # payAmt = 票价 + 手续费
        pay_amt = int(self.basePrice) + int(getattr(self, "rsrvFee", 0))
        # chkAgree 需要多个相同 key，使用 list of tuples
        payload_items = [
            ('jType', 'I'),
            ('delvyTypeCode', 'DV0002'),  # 现场取票
            ('tel', self.phone),
            ('email', self.user_id),
            ('payMethodCode', 'AP0012'),
            ('cardCode', 'FOREIGN_CHINABANK'),
            ('cardCodeName', 'UnionPay'),
            ('autheTypeCode', 'AT0005'),
            ('cardQuota', '00'),
            ('quota', '00'),
            ('chkAgreeAll', 'on'),
            ('chkAgree', 'on'),
            ('chkAgree', 'on'),
            ('chkAgree', 'on'),
            ('chkAgree', 'on'),
            ('chkAgree', 'on'),
            ('chkAgree', 'on'),
            ('prodId', self.prod_id),
            ('pocCode', 'SC0002'),
            ('scheduleNo', self.scheduleNo),
            ('rsrvVolume', 1),
            ('payAmt', pay_amt),
            ('priceNo', self.priceNo),
            ('seatId', self.seat_id),
            ('seatInfoListWithPriceType', json.dumps([seat_info])),
            ('firstSeatId', self.seat_id),
            ('sellTypeCode', 'ST0001'),
            ('chkcapt', getattr(self, 'chkcapt', '')),
        ]

        try:
            resp = self.session.post(
                url,
                params={"v": "1", "callback": "saveHandler"},
                data=payload_items,
            )
            if resp.status_code == 200:
                resp.raise_for_status()
                save_order_data = parse_jsonp("saveHandler", resp.text)
                code = save_order_data.get("code")
                if code != "0000":
                    logger.warning(f"⚠️ 保存订单失败,接口返回 code: {code}, message: {save_order_data.get('message')}")
                    return None
                rsrv_seq = save_order_data.get("rsrvSeq")
                pay_no = save_order_data.get("payNo")
                logger.info(f"✅ 订单保存成功！rsrvSeq={rsrv_seq}, payNo={pay_no}")
                return rsrv_seq
            else:
                logger.error(f"❌ 保存订单失败, 状态码: {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"💥 保存订单异常: {e}")
            return None

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