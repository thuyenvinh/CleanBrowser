"""Smoke tests for RemoteWorker scaffold.

These do not exercise real gRPC; they only verify construction and Protocol
compliance. Network calls would require grpcio + a live worker_server.
"""
from __future__ import annotations


def test_remote_worker_construction():
    from backend.worker_remote import RemoteWorker
    w = RemoteWorker("w-1", "us-east", "127.0.0.1:50051")
    assert w.worker_id == "w-1"
    assert w.region == "us-east"
    assert w.address == "127.0.0.1:50051"
    assert w._stub is None
    assert w._channel is None


def test_remote_worker_protocol_compliance():
    from backend.worker import Worker
    from backend.worker_remote import RemoteWorker
    w = RemoteWorker("w-1", "us-east", "127.0.0.1:50051")
    assert isinstance(w, Worker)


def test_remote_worker_exported_from_worker_module():
    from backend.worker import RemoteWorker as RW1
    from backend.worker_remote import RemoteWorker as RW2
    assert RW1 is RW2


def test_grpc_proto_stubs_importable():
    from backend.grpc_proto import worker_pb2, worker_pb2_grpc
    req = worker_pb2.LaunchRequest(profile_id="p-1")
    assert req.profile_id == "p-1"
    reply = worker_pb2.CapacityReply(worker_id="w", region="r", max_profiles=5)
    assert reply.max_profiles == 5
    # Stub raises NotImplementedError on RPC call without real generation.
    stub = worker_pb2_grpc.WorkerServiceStub(channel=None)
    import pytest
    with pytest.raises(NotImplementedError):
        stub.Launch(req)
