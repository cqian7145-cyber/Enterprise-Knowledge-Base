"""Bound unsafe request bodies even without Content-Length (chunked requests)."""
from starlette.responses import PlainTextResponse


class RequestLimitMiddleware:
    def __init__(self, app, max_bytes=131072):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in ('GET', 'HEAD', 'OPTIONS'):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        length = headers.get(b'content-length')
        if length is not None:
            if not length.isdigit():
                return await PlainTextResponse('Invalid Content-Length', status_code=400)(scope, receive, send)
            significant = length.lstrip(b'0') or b'0'
            if len(significant) > 6 or int(significant) > self.max_bytes:
                return await PlainTextResponse('Request too large', status_code=413)(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > self.max_bytes:
                return await PlainTextResponse('Request too large', status_code=413)(scope, receive, send)
            messages.append(message)
            if not message.get('more_body', False):
                break
        messages = iter(messages)

        async def replay():
            try:
                return next(messages)
            except StopIteration:
                return await receive()

        return await self.app(scope, replay, send)
