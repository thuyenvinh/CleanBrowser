"""Stub - real grpc stubs require grpcio-tools. See README in this directory.

This module provides minimal placeholders so that import-time references in
``worker_remote.py`` and ``worker_server.py`` do not fail in environments
without grpcio. All RPC methods raise NotImplementedError at call time. To
generate real stubs, run the command in README.md.
"""
from __future__ import annotations


_REGEN_HINT = (
    "Real gRPC stubs not generated. Run:\n"
    "  python -m grpc_tools.protoc -I backend/grpc_proto "
    "--python_out=backend/grpc_proto --grpc_python_out=backend/grpc_proto "
    "backend/grpc_proto/worker.proto"
)


class WorkerServiceStub:
    def __init__(self, channel):
        self.channel = channel

    def Launch(self, request):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def Stop(self, request):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def Status(self, request):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def Capacity(self, request):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def IsRunning(self, request):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def CdpUrl(self, request):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)


class WorkerServiceServicer:
    def Launch(self, request, context):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def Stop(self, request, context):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def Status(self, request, context):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def Capacity(self, request, context):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def IsRunning(self, request, context):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)

    def CdpUrl(self, request, context):  # pragma: no cover - stub
        raise NotImplementedError(_REGEN_HINT)


def add_WorkerServiceServicer_to_server(servicer, server):  # pragma: no cover - stub
    """Placeholder; real impl registers handlers with the grpc server."""
    return None
