# Security policy

This repository holds the specification, its conformance suite, and the
tools that check them. It ships no runtime: a vulnerability in an engine
belongs in [get-milano/sdk](https://github.com/get-milano/sdk/security),
which is where the code that runs on a device lives.

What is worth reporting here is a defect in the contract itself: a rule
whose wording lets a conformant engine accept something dangerous, a limit
that does not bound what it claims to, or a vector that pins behaviour the
prose forbids. A specification that permits an unsafe engine is a
specification bug, and it is the more serious kind, because every engine
implements it faithfully.

## Reporting

Use GitHub's private vulnerability reporting on this repository: the
**Security** tab, then **Report a vulnerability**. Please do not open a
public issue for a suspected vulnerability.

Include the section of the specification, what a conformant engine is
permitted to do under it, and why that is unsafe. A conformance vector that
demonstrates it is the fastest possible report.

You should get an acknowledgement within a week. A fix here means changed
normative text plus the vectors that pin it, and then the engines follow in
the SDK.

## Supported versions

The latest repository release of the current contract major. Older contract
majors are not maintained.
