"""gRPC server that exposes a LocalWorker over the network.

Run on each worker pod:

    python -m backend.worker_server --port 50051 --worker-id w-0 --region us-east
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .worker import LocalWorker

logger = logging.getLogger(__name__)


class WorkerServicer:  # implements WorkerServiceServicer
    def __init__(self, local: LocalWorker):
        self.local = local

    async def Launch(self, request, context):
        from .grpc_proto import worker_pb2
        try:
            r = await self.local.launch(request.profile_id)
            return worker_pb2.LaunchReply(
                session_id=r.session_id,
                worker_id=r.worker_id,
                cdp_port=r.cdp_port,
                vnc_port=r.vnc_port,
                display_num=r.display_num,
            )
        except Exception as e:
            return worker_pb2.LaunchReply(error=str(e))

    async def Stop(self, request, context):
        from .grpc_proto import worker_pb2
        try:
            await self.local.stop(request.profile_id)
            return worker_pb2.StopReply()
        except Exception as e:
            return worker_pb2.StopReply(error=str(e))

    async def Status(self, request, context):
        from .grpc_proto import worker_pb2
        s = await self.local.status(request.profile_id)
        return worker_pb2.StatusReply(**{k: v for k, v in s.items() if v is not None})

    async def IsRunning(self, request, context):
        from .grpc_proto import worker_pb2
        return worker_pb2.IsRunningReply(
            running=await self.local.is_running(request.profile_id)
        )

    async def CdpUrl(self, request, context):
        from .grpc_proto import worker_pb2
        url = await self.local.cdp_url(request.profile_id)
        return worker_pb2.CdpUrlReply(cdp_url=url or "")

    async def Capacity(self, request, context):
        from .grpc_proto import worker_pb2
        c = await self.local.capacity()
        return worker_pb2.CapacityReply(
            worker_id=c.worker_id,
            region=c.region,
            max_profiles=c.max_profiles,
            running_count=c.running_count,
            cpu_percent=c.cpu_percent or 0.0,
            ram_mb_used=c.ram_mb_used or 0,
        )


async def serve(port: int, worker_id: str, region: str):
    try:
        import grpc
        from .grpc_proto import worker_pb2_grpc
    except ImportError:
        raise SystemExit("grpcio not installed; pip install grpcio")
    server = grpc.aio.server()
    local = LocalWorker(worker_id=worker_id, region=region)
    worker_pb2_grpc.add_WorkerServiceServicer_to_server(
        WorkerServicer(local), server
    )
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    logger.info(
        "worker server listening on :%d worker_id=%s region=%s",
        port, worker_id, region,
    )
    await server.wait_for_termination()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--worker-id", default="w-0")
    parser.add_argument("--region", default="local")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(args.port, args.worker_id, args.region))


if __name__ == "__main__":
    main()
