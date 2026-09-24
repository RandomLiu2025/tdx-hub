class TdxConnectionError(Exception):
    """
    当连接服务器出错的时候，会抛出的异常
    """

    pass


class TdxFunctionCallError(Exception):
    """
    当行数调用出错的时候
    """

    def __init__(self, *args):
        super().__init__(*args)
        self.original_exception = None


class ValidationException(Exception): ...


class ProtocolError(TdxFunctionCallError):
    """Malformed or incomplete wire response, eligible for existing failover."""


class SocketClientNotReady(Exception):
    pass


class SendPkgNotReady(Exception):
    pass


class SendRequestPkgFails(ProtocolError):
    pass


class ResponseHeaderRecvFails(ProtocolError):
    pass


class ResponseRecvFails(ProtocolError):
    pass
