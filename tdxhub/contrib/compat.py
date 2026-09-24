import socket
import threading

from tdxhub.logger import logger
from tdxhub.tdx.errors import TdxConnectionError
from tdxhub.tdx.files import TdxDailyBarReader
from tdxhub.tdx.heartbeat import HeartBeatThread
from tdxhub.tdx.transport import CONNECT_TIMEOUT, BaseSocketClient, TrafficStatSocket

TdxhubDailyBarReader = TdxDailyBarReader


class TdxhubBaseSocketClient(BaseSocketClient):
    def __init__(self):
        super().__init__()
        self.client = None

    def connect(self, ip='101.227.73.20', port=7709, time_out=CONNECT_TIMEOUT, bindport=None, bindip='0.0.0.0'):
        """

        :param ip:  服务器ip 地址
        :param port:  服务器端口
        :param time_out: 连接超时时间
        :param bindport: 绑定的本地端口
        :param bindip: 绑定的本地ip
        :return: 是否连接成功 True/False
        """

        self.client = TrafficStatSocket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.settimeout(time_out)

        logger.debug('connecting to server : %s on port :%d' % (ip, port))

        try:
            self.ip = ip
            self.port = port

            if bindport is not None:
                self.client.bind((bindip, bindport))

            self.client.connect((ip, port))
        except socket.timeout as e:
            logger.debug(e)
            logger.debug('connection expired')

            if self.raise_exception:
                raise TdxConnectionError('connection timeout error')

            return False
        except Exception as e:
            logger.debug(e)
            if self.raise_exception:
                raise TdxConnectionError('other errors')

            return False

        logger.debug('connected!')

        if self.need_setup:
            self.setup()

        if self.heartbeat:
            self.stop_event = threading.Event()
            self.heartbeat_thread = HeartBeatThread(self, self.stop_event, self.heartbeat_interval)
            self.heartbeat_thread.start()

        return self

    def disconnect(self):

        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.stop_event.set()

        if self.client:
            logger.debug('disconnecting')

            try:
                self.client.shutdown(socket.SHUT_RDWR)
                self.client.close()
                self.client = None
            except Exception as e:
                logger.debug(str(e))

                if self.raise_exception:
                    raise TdxConnectionError('disconnect err')

            logger.debug('disconnected')

    def setup(self):
        pass
