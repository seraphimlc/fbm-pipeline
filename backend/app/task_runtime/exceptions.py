class TaskStepCanceled(RuntimeError):
    """Raised by a worker when a cancel request should stop success projection."""


class TaskStepInterrupted(RuntimeError):
    """Raised when a running step is interrupted before normal completion."""
