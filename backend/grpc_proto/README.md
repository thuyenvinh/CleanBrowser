# worker gRPC stubs

`worker_pb2.py` and `worker_pb2_grpc.py` in this directory are minimal hand-
written stubs so the rest of the codebase imports cleanly without grpcio
installed. To generate the real protobuf/gRPC modules, install
`grpcio-tools` and run from this directory:

```
python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. worker.proto
```

Or from the repo root:

```
python -m grpc_tools.protoc -I backend/grpc_proto \
    --python_out=backend/grpc_proto \
    --grpc_python_out=backend/grpc_proto \
    backend/grpc_proto/worker.proto
```

Commit the generated files (or run as a build step in CI). The stub
implementations raise `NotImplementedError` at RPC call time so accidental
use in production without real generation fails loudly.
