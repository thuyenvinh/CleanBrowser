"""RemoteWorker - gRPC client wrapping a remote worker pod.

Use case: control plane API process talks to N worker pods running
browser_manager + KasmVNC. Each pod registers via its address; the
control plane round-robins / selects by region + capacity.
"""
from __future__ import annotations

from .worker import WorkerCapacity, LaunchResult  # noqa: F401  (re-exported types)


class RemoteWorker:
    worker_id: str
    region: str

    def __init__(self, worker_id: str, region: str, address: str):
        self.worker_id = worker_id
        self.region = region
        self.address = address
        self._channel = None
        self._stub = None

    def _connect(self):
        if self._stub is None:
            try:
                import grpc
                from .grpc_proto import worker_pb2_grpc
            except ImportError as e:
                raise RuntimeError(f"grpc not installed: {e}")
            self._channel = grpc.aio.insecure_channel(self.address)
            self._stub = worker_pb2_grpc.WorkerServiceStub(self._channel)
        return self._stub

    async def launch(self, profile_id: str) -> LaunchResult:
        from .grpc_proto import worker_pb2
        stub = self._connect()
        reply = await stub.Launch(worker_pb2.LaunchRequest(profile_id=profile_id))
        if reply.error:
            raise RuntimeError(f"remote launch failed: {reply.error}")
        return LaunchResult(
            session_id=reply.session_id,
            worker_id=reply.worker_id,
            cdp_port=reply.cdp_port,
            vnc_port=reply.vnc_port,
            display_num=reply.display_num,
        )

    async def stop(self, profile_id: str) -> None:
        from .grpc_proto import worker_pb2
        stub = self._connect()
        reply = await stub.Stop(worker_pb2.StopRequest(profile_id=profile_id))
        if reply.error:
            raise RuntimeError(reply.error)

    async def status(self, profile_id: str) -> dict:
        from .grpc_proto import worker_pb2
        stub = self._connect()
        reply = await stub.Status(worker_pb2.StatusRequest(profile_id=profile_id))
        return {
            "running": reply.running,
            "session_id": reply.session_id,
            "worker_id": reply.worker_id,
            "cdp_port": reply.cdp_port,
            "vnc_port": reply.vnc_port,
        }

    async def is_running(self, profile_id: str) -> bool:
        from .grpc_proto import worker_pb2
        stub = self._connect()
        reply = await stub.IsRunning(worker_pb2.IsRunningRequest(profile_id=profile_id))
        return reply.running

    async def cdp_url(self, profile_id: str) -> str | None:
        from .grpc_proto import worker_pb2
        stub = self._connect()
        reply = await stub.CdpUrl(worker_pb2.CdpUrlRequest(profile_id=profile_id))
        return reply.cdp_url or None

    async def capacity(self) -> WorkerCapacity:
        from .grpc_proto import worker_pb2
        stub = self._connect()
        reply = await stub.Capacity(worker_pb2.CapacityRequest())
        return WorkerCapacity(
            worker_id=reply.worker_id,
            region=reply.region,
            max_profiles=reply.max_profiles,
            running_count=reply.running_count,
            cpu_percent=reply.cpu_percent or None,
            ram_mb_used=reply.ram_mb_used or None,
        )

    async def close(self):
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
