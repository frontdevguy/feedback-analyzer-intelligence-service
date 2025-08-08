def setup_routes(app, config, services):
    from . import reply, health

    # Health check routes
    app.include_router(health.router, prefix="/health", tags=["health"])

    # Application routes
    app.include_router(reply.router, prefix="/reply", tags=["reply"])
    reply.router.config = config
    reply.router.services = services
