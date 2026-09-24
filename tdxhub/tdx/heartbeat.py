import time
from threading import Thread

from tdxhub.tdx.logger import logger

# 10秒一个heartbeat
DEFAULT_HEARTBEAT_INTERVAL = 10.0


class HeartBeatThread(Thread):
    # 参考 :https://stackoverflow.com/questions/6524459/stopping-a-thread-after-a-certain-amount-of-time

    def __init__(self, client, stop_event, interval=DEFAULT_HEARTBEAT_INTERVAL):
        """
        初始化
        :param client: 客户端主进程
        :param stop_event: 停止事件进程
        :param interval: 心跳周期
        """

        self.heartbeat_interval = interval
        self.stop_event = stop_event

        self.client = client.client
        self.api = client

        super().__init__()

    def run(self):
        # stop_event 未设置就执行
        while not self.stop_event.is_set():
            # 客户端主进程 and 满足 heartbeat_interval
            if self.client and (time.monotonic() - self.api.last_ack_time > self.heartbeat_interval):
                try:
                    # 发送一个获取股票数量的包作为心跳包
                    logger.debug("发送一个获取股票数量的包作为心跳包...")
                    runner = getattr(self.api, "heartbeat_runner", None)
                    if runner is not None:
                        runner()
                    else:
                        self.api.do_heartbeat()
                except Exception as e:
                    logger.exception(str(e))
                    callback = getattr(self.api, "heartbeat_error_callback", None)
                    if callback is not None:
                        callback(e)
                        self.stop_event.set()

            # 等待心跳周期
            self.stop_event.wait(self.heartbeat_interval)
