"""InsightFace model loading, cached per-process."""
from __future__ import annotations

_APP = None


def get_face_app(intra_op_threads: int | None = None):
    """Lazily load & cache the InsightFace FaceAnalysis app (buffalo_l, CPU).

    intra_op_threads: when running one worker PROCESS per CPU core (the CLI's
    `find` command design), each ONNX Runtime session should use a SINGLE
    intra-op thread. Left at ORT's default (which sizes its intra-op pool to
    all physical cores), N worker processes would each spin up an N-core-wide
    threadpool, causing massive oversubscription and context-switch thrashing
    once N > 1. Pinning threads=1 here and getting parallelism from the
    process pool instead scales far better for many small, independent
    single-image inferences (each call is cheap, so per-call thread-pool
    scheduling overhead in the multi-threaded case dominates anyway).
    """
    global _APP
    if _APP is None:
        import onnxruntime as ort
        from insightface.app import FaceAnalysis

        kwargs = {"providers": ["CPUExecutionProvider"]}
        if intra_op_threads:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = intra_op_threads
            sess_options.inter_op_num_threads = 1
            kwargs["sess_options"] = sess_options

        _APP = FaceAnalysis(name="buffalo_l", **kwargs)
        _APP.prepare(ctx_id=0, det_size=(640, 640))
    return _APP
