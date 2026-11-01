# EnCodec isolated compatibility environment

This lock is a non-installed P9 compatibility declaration. It pins the
optional EnCodec adapter away from the QSTE core environment. P9 did not sync
this environment, download its checkpoint, import its package, or execute its
model.

The lock alone does not make the adapter executable. Execution remains
unavailable until a separately authorized operator supplies the exact local
checkpoint and environment, the probe verifies their digests, and the
checkpoint's aggregate license status is resolved. Disabling this adapter
requires removing its profile from a run configuration; foundation replay has
no dependency on this environment.

## Security hold — 2026-11-01

The frozen reference above is historical compatibility evidence, not a current
installation recommendation. Its PyTorch 2.11.0, setuptools 81.0.0 and filelock
3.32.4 resolve to published advisory matches. Do not synchronize or execute this
snapshot as a maintained environment.

This security update preserves the P9 lock and its bound digest. A patched
successor can use PyTorch 2.13.0 with TorchAudio 2.11 under upstream's
[stable ABI compatibility guidance](https://docs.pytorch.org/audio/stable/installation.html).
A matching TorchAudio 2.13 release is not required. Patched filelock 4.2.1 also
requires Python 3.11 or later, so the successor must revise the old Python
3.10-compatible declaration as well.

The successor needs a separately versioned compatibility target, patched
dependency lock and qualification on the intended platform before replacing
this reference. Checkpoint provenance, license resolution and existing execution
authorization gates still apply. No checkpoint download, environment
synchronization or model execution is included in this update.
