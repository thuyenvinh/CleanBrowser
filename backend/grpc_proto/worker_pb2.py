"""Stub - real grpc stubs require grpcio-tools. See README in this directory.

These dataclasses mirror the messages in worker.proto so that import works in
environments without grpcio installed. When grpcio-tools is available, run the
regeneration command in README.md to overwrite this file with the real
protobuf-generated module.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class LaunchRequest:
    profile_id: str = ""


@dataclass
class LaunchReply:
    session_id: str = ""
    worker_id: str = ""
    cdp_port: int = 0
    vnc_port: int = 0
    display_num: int = 0
    error: str = ""


@dataclass
class StopRequest:
    profile_id: str = ""


@dataclass
class StopReply:
    error: str = ""


@dataclass
class StatusRequest:
    profile_id: str = ""


@dataclass
class StatusReply:
    running: bool = False
    session_id: str = ""
    worker_id: str = ""
    cdp_port: int = 0
    vnc_port: int = 0


@dataclass
class CapacityRequest:
    pass


@dataclass
class CapacityReply:
    worker_id: str = ""
    region: str = ""
    max_profiles: int = 0
    running_count: int = 0
    cpu_percent: float = 0.0
    ram_mb_used: int = 0


@dataclass
class IsRunningRequest:
    profile_id: str = ""


@dataclass
class IsRunningReply:
    running: bool = False


@dataclass
class CdpUrlRequest:
    profile_id: str = ""


@dataclass
class CdpUrlReply:
    cdp_url: str = ""
