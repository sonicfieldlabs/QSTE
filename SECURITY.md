# Security policy

QSTE is pre-release research software. No version currently has a supported
public security lifecycle.

## Reporting

Use a private GitHub security advisory for vulnerabilities, credential
exposure, unsafe filesystem behavior, policy bypass, provenance corruption, or
audio-output hazards. Do not place secrets, restricted source details, or
participant information in a public issue.

## P1 security posture

- the package exposes no server or network listener;
- the shipped command reports version and repository identity only;
- runtime modules declare their capability unavailable;
- generated material and private data are ignored by Git;
- adjacent repositories are outside the write boundary; and
- no paper, schema, bundle, or replay claim is treated as proof of safe
  execution.

Future state-changing or rendering operations require explicit roots,
authorization, resource bounds, validation, and an operation receipt.
