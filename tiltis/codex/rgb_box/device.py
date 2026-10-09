"""Explicit compute selection; requesting CUDA never silently uses the CPU."""


def select_device(requested, torch):
    if requested not in ("cpu", "cuda"):
        raise ValueError("device must be cpu or cuda")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU unavailable: select a GPU runtime in Colab first")
    return requested


def synchronize(torch, device):
    if device == "cuda":
        torch.cuda.synchronize()
