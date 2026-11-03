# EnCodec dependency successor 0.2

This separately locked Python 3.12 candidate replaces affected dependency
versions for qualification without changing the frozen P9 reference or selecting
a new executable adapter. It pins Torch 2.13.0, stable-ABI TorchAudio 2.11.0 and
TorchCodec 0.17.0, with patched filelock/setuptools floors. EnCodec 0.1.1,
its source identity and its package/checkpoint license uncertainties are retained.

`compatibility-target.json` binds this lock and the exact historical reference
files. The current adapter still points to its original profile. Checkpoint
download, adapter activation and model execution remain unauthorized. Resolving
the checkpoint license and qualifying actual model behavior require their own
operator evidence; dependency CI does not satisfy those gates.

The macOS CI probe installs the exact candidate, rejects fresh PyPI advisory or
artifact-digest mismatches, then blocks socket connections/model downloads while
checking SDK imports and generated CPU WAV encode/decode geometry and finite
values. It never constructs an EnCodec model, loads a checkpoint, runs inference,
captures audio or establishes listening/scientific results. No Linux/CUDA/MPS,
installed operator environment or checkpoint compatibility is claimed.

The macOS ARM runtime is the checksum-pinned Python Build Standalone 20261026
build of Python 3.12.16. This keeps the maintained patch even where GitHub's
Python setup action does not provide that platform build. The core CI matrix
continues to use its existing Python setup action.

Source builds of EnCodec use the already locked setuptools environment in the
disposable runner. The core environment, package version, frozen schemas,
fixtures, profiles and original EnCodec environment are unchanged.

Upstream compatibility: https://docs.pytorch.org/audio/stable/installation.html
and https://github.com/pytorch/torchcodec#compatibility-with-torch-versions.
