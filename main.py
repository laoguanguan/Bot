from playwright.sync_api import sync_playwright
from core.session_manager import SessionManager
from core.ticket_bot import TicketBot, TicketBotConfig

def main():
    config = TicketBotConfig(
        target_url="https://ticket.melon.com/performance/index.htm?prodId=XXXXX",
        open_time="2026-03-15 20:00:00",
        seat_keywords=["A", "B"]
    )
    
    account_id = "user01" # 你的账号标识

    with sync_playwright() as p:
        # 1. 启动浏览器 (必须 headless=False 以便首次登录)
        browser = p.chromium.launch(headless=False)
        
        # 2. 初始化 Session 管理器并获取登录态 Context
        session_mgr = SessionManager(browser, account_id=account_id)
        context = session_mgr.load_or_create_context()
        
        # 3. 基于已登录的 Context 启动抢票 Bot
        bot = TicketBot(context, config)
        
        try:
            bot.run()
        except KeyboardInterrupt:
            bot.stop()
        finally:
            # 如果抢到了，保持浏览器打开让用户支付
            if not bot.success:
                browser.close()
            else:
                print("🎉 抢票成功！请手动完成支付。浏览器将保持打开...")
                input("按回车键退出...")
                browser.close()

if __name__ == "__main__":
    main()