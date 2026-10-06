"""CPU thread settings shared by the models."""
import os


def cpu_threads():
    """CPU_THREADS caps the threads each model uses (0 = the library's default). A container often
    reports the host's cores rather than its own share, and too many threads slow inference down."""
    try:
        return max(0, int(os.getenv("CPU_THREADS", "0")))
    except ValueError:
        return 0


def onnx_session(onnxruntime, path):
    options = onnxruntime.SessionOptions()
    if cpu_threads():
        options.intra_op_num_threads = cpu_threads()
    return onnxruntime.InferenceSession(path, options, providers=["CPUExecutionProvider"])
