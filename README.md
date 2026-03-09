1. config/settings.py
存放非敏感配置：目标 URL、抢票时间、座位偏好、重试次数、请求间隔等。
可通过 argparse 或 click 支持命令行参数覆盖。
2. core/ticket_bot.py
主逻辑：登录 → 检查余票 → 提交订单 → 支付（如有）
包含重试机制、异常捕获、状态机（如：未开售 → 开始抢 → 成功/失败）
3. core/session_manager.py
使用 requests.Session() 或 httpx.AsyncClient 维护 Cookie 和 headers
自动处理登录态刷新
4. api/xxx_api.py
封装目标平台的接口（如查询余票、下单、获取验证码等）
模块化设计，便于切换不同平台（如 12306 vs 大麦）
5. utils/captcha_solver.py
若有验证码，可接入第三方打码平台（如超级鹰、云打码）或使用 OCR（如 ddddocr）
也可支持手动输入（开发/测试阶段）
6. utils/notify.py
抢票成功/失败时发送通知（推荐使用 Server 酱、Bark、Telegram Bot）
7. core/scheduler.py
使用 APScheduler 或 threading.Timer 在指定时间启动抢票
支持“提前 N 秒进入准备状态”以减少延迟
⚠️ 注意事项
合法性：确保遵守目标网站的《用户协议》，避免高频请求被封 IP。
反爬机制：很多票务平台有风控（如滑块验证、设备指纹），需模拟真实浏览器（可考虑集成 playwright 或 selenium）。
性能优化：关键路径尽量用异步（asyncio + httpx）提升并发能力。
日志与调试：详细记录每一步响应，便于排查问题。
不要硬编码账号密码：使用环境变量或加密配置文件。