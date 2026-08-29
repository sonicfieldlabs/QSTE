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
