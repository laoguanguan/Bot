import requests
import time
import json
from urllib.parse import urljoin

class MelonTicketBot:
    def __init__(self):
        # 创建一个 Session 对象，它会自动保存 Cookie！
        self.session = requests.Session()
        
        # 基础 Headers (所有请求共用)
        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "X-Requested-With": "XMLHttpRequest", # 关键：标识 Ajax 请求
            "Accept": "text/javascript, application/javascript, application/ecmascript, application/x-ecmascript, */*; q=0.01"
        }
        self.session.headers.update(self.base_headers)

        # 配置信息
        self.config = {
            "base_url": "https://tkglobal.melon.com",
            "prodid": "212838",
            "scheduleNo": "100003",
            "username": "", # 替换为你的账号
            "password": "YOUR_PASSWORD" # 替换为你的密码
        }

    def step_login(self):
        """
        步骤 1: 登录
        注意：Melon 的登录接口可能涉及加密或验证码，这里演示标准流程。
        如果有验证码，通常需要手动登录一次，然后复制 Cookie 到代码中。
        """
        print("? [步骤 1] 正在尝试登录...")
        
        # 真实的登录 URL (需要根据抓包确认，通常是 POST)
        login_url = "https://www.melon.com/member/login/login.json" 
        # 注意：如果是 tkglobal，登录逻辑可能不同，有时需要先在主站登录再跳过去
        
        payload = {
            "userId": self.config["username"],
            "userPwd": self.config["password"],
            "urlParams": "" # 可能需要回调地址
        }
        
        # 更新 Referer 为登录页
        self.session.headers["Referer"] = "https://www.melon.com/member/login.html"
        
        try:
            # 发送登录请求
            resp = self.session.post(login_url, data=payload)
            
            # 检查是否登录成功 (通常看响应里的 success 字段，或者看是否有 JSESSIONID)
            if "JSESSIONID" in self.session.cookies:
                print("? 登录成功！Cookie 已自动保存到 Session 中。")
                return True
            else:
                # 尝试检查响应内容判断失败原因
                print(f"?? 登录可能失败或未获取到 Session Cookie。响应: {resp.text[:100]}")
                # 如果自动登录困难，建议手动登录后复制 Cookie
                return False
        except Exception as e:
            print(f"? 登录出错: {e}")
            return False

    def step_visit_detail(self):
        """
        步骤 2: 访问演出详情页
        目的：让服务器知道我们在看这个演出，并确立合法的 Referer 来源。
        """
        print(f"? [步骤 2] 正在访问详情页 (prodid: {self.config['prodid']})...")
        
        detail_url = f"{self.config['base_url']}/performance/index.htm?langCd=EN&prodid={self.config['prodid']}"
        
        # 设置 Referer 为首页或上一级
        self.session.headers["Referer"] = f"{self.config['base_url']}/performance/main.htm"
        
        # 移除 X-Requested-With，因为访问 HTML 页面通常不需要这个头，或者是浏览器自动加的
        # 但为了保险，我们可以保留，或者让 requests 默认处理
        # 这里我们显式访问一个 HTML 页面，通常不需要 Accept: application/json
        
        temp_headers = self.base_headers.copy()
        temp_headers.pop("X-Requested-With", None) # 访问 HTML 时去掉这个
        temp_headers["Accept"] = "text/html,application/xhtml+xml..."
        
        try:
            resp = self.session.get(detail_url, headers=temp_headers)
            if resp.status_code == 200:
                print("? 详情页访问成功。服务器已记录当前上下文。")
                # 此时，self.session.cookies 里可能多了新的临时 Token
                return True
            else:
                print(f"? 详情页访问失败: {resp.status_code}")
                return False
        except Exception as e:
            print(f"? 访问详情页出错: {e}")
            return False

    def step_3_check_tickets(self):
        """
        步骤 3: 查询余票 (核心业务)
        关键：使用之前 Step 2 建立的 Referer 和 Step 1 的 Cookie
        """
        print("? [步骤 3] 正在查询余票...")
        
        api_url = f"{self.config['base_url']}/tkapi/glb/product/schedule/gradelist.json"
        
        params = {
            "callback": "scheduleList4",
            "v": "1",
            "prodid": self.config["prodid"],
            "pocCode": "SC0002",
            "scheduleNo": self.config["scheduleNo"],
            "perfTypeCode": "GN0001",
            "sellTypeCodeData": "ST0001",
            "langCd": "EN",
            "seatCntDisplayN": "N"
        }
        
        # 【最关键的一步】设置 Referer 为刚才访问过的详情页 URL
        # 服务器会校验：你必须是刚从详情页过来的，才能查这个场次的票
        self.session.headers["Referer"] = f"{self.config['base_url']}/performance/index.htm?langCd=EN&prodid={self.config['prodid']}"
        self.session.headers["X-Requested-With"] = "XMLHttpRequest" # 加回来
        self.session.headers["Accept"] = "text/javascript, application/javascript, application/ecmascript, application/x-ecmascript, */*; q=0.01"
        
        try:
            resp = self.session.get(api_url, params=params)
            
            if resp.status_code == 200:
                text = resp.text
                if text.startswith("scheduleList4("):
                    json_str = text[len("scheduleList4("):-1]
                    data = json.loads(json_str)
                    
                    # 简单解析余票
                    if 'data' in data and 'gradeInfo' in data['data']:
                        print("? 获取到余票数据：")
                        for grade in data['data']['gradeInfo']:
                            print(f"   - {grade.get('gradeName')}: 剩余 {grade.get('seatCnt')} 张")
                        return data
                    else:
                        print("?? 数据格式异常")
                else:
                    print(f"?? 非 JSONP 响应: {text[:50]}")
            else:
                print(f"? 查询失败，状态码: {resp.status_code}")
                # 如果返回 403 或 302，通常是因为 Referer 不对或 Cookie 过期
                if "Referer" in resp.request.headers:
                    print(f"   当前使用的 Referer: {resp.request.headers['Referer']}")
            
            return None
        except Exception as e:
            print(f"? 查询出错: {e}")
            return None

    def run_full_flow(self):
        """执行完整流程"""
        print("? 开始模拟用户购票全流程...\n")
        
        # 1. 登录 (获取 Cookie)
        if not self.step_1_login():
            print("? 提示：如果自动登录失败，请在浏览器登录 Melon，复制 Cookie 手动填入代码。")
            # 这里可以添加手动输入 Cookie 的逻辑作为备选
            return

        # 2. 访问详情页 (建立上下文)
        if not self.step_2_visit_detail():
            return

        # 3. 查询余票 (业务逻辑)
        data = self.step_3_check_tickets()
        
        if data:
            print("\n? 流程跑通！接下来可以将 step_3 放入循环进行监控。")
        else:
            print("\n?? 流程中断，请检查日志。")

if __name__ == "__main__":
    bot = MelonTicketBot()
    bot.run_full_flow()