"""Pinned Uvicorn HTTP/1.1 transport exposes verified client certificates to ASGI."""
import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol
from .tls import ensure_identity, server_context


class TLSProtocol(H11Protocol):
    def connection_made(self, transport):
        super().connection_made(transport)
        ssl_object=transport.get_extra_info('ssl_object')
        der=ssl_object.getpeercert(binary_form=True) if ssl_object else None
        app=self.app
        async def with_certificate(scope,receive,send):
            scope=dict(scope)
            scope['extensions']={**scope.get('extensions',{}),'hemlock.client_certificate':der}
            await app(scope,receive,send)
        self.app=with_certificate


def make_server(config,*,adapter=None,background=True):
    from .web import create_app
    identity=ensure_identity(config)
    context=server_context(config)
    restarted={'requested':False}
    def restart():
        restarted['requested']=True;server.should_exit=True
    app=create_app(config,adapter=adapter,background=background,tls_context=context,tls_restart=restart,tls_rotation=identity.get('rotation_event'))
    settings=uvicorn.Config(app,host=config.host,port=config.port,workers=1,http=TLSProtocol,
                            ssl_certfile=config.cert,ssl_keyfile=config.key,proxy_headers=False,access_log=False,timeout_graceful_shutdown=30)
    settings.load();settings.ssl=context
    server=uvicorn.Server(settings)
    server.tls_restart_state=restarted
    return server


def serve(config):
    while True:
        server=make_server(config)
        server.run()
        if not server.started:raise RuntimeError('HTTPS server did not start')
        if not server.tls_restart_state['requested']:break
