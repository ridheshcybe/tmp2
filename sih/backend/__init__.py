"""
AeroTwin backend package.

Making this an explicit package (rather than relying on namespace packages)
matters for more than tidiness.  The app used to be startable two ways - as
``main:app`` from this directory, or as ``backend.main:app`` from the repo
root - and those load every module twice under two different names.  The two
copies each get their own ``Settings`` singleton and their own
``websocket_handler._manager``, so a fault broadcast through
``backend.websocket_handler`` never reaches clients registered through
``websocket_handler``.

One name, one package: run it from the repository root as::

    python -m uvicorn backend.main:app --port 8081
"""
