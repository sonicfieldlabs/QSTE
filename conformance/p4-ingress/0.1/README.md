# P4 ingress conformance 0.1

This profile tests the first bounded QSTE data boundary. It is additive to the
normative `qste-contract/0.3.0` schema set and does not redefine those schemas.

Run `make ingress-contracts`. A pass establishes only the claims enumerated in
`ingress-profile.json`; it does not establish transduction, representation,
quanta, or runtime capability.
