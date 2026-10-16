#!/usr/bin/env python3
"""
Build a SMART Health Card (.smart-health-card) of lab results that the iPhone Health app will import.

Usage:
    python make_shc.py spec.json out.smart-health-card [--key issuer-key.pem]

Needs: pip install cryptography

spec.json (see examples/shc_spec_example.json):
{
  "iss": "https://github.com/you/your-repo",     # https URL; Health tries <iss>/.well-known/jwks.json
  "patient": {"family": "Doe", "given": ["Jane"], "birthDate": "YYYY-MM-DD"},   # birthDate optional
  "observations": [
    {"loinc": "706-2", "display": "Basophils/100 leukocytes in Blood by Automated count",
     "date": "2026-06-07", "value": 0.7, "unit": "%", "low": null, "high": null}
  ]
}

What you get, and what you don't (tested on iOS 27.2 beta, Oct 2026):
- Health imports the card (open it from Files, Mail or AirDrop, not straight from a cloud-storage app)
  as one "Lab Result Record" under Browse > Lab Results, marked "Not Verified" because the issuer is
  not in the VCI directory. The values get history charts there.
- Longevity > Labs does NOT count these results: its panels (e.g. Blood Health "4 of 20 markers")
  are unchanged after the import. Use the manual lab-entry forms for the core markers.
- An import can only be deleted as a whole.

The card follows the SMART Health Cards spec: types health-card + laboratory, a FHIR 4.0.1 collection
Bundle (Patient + Observations with LOINC codes and UCUM valueQuantity/referenceRange), raw-DEFLATE
compressed payload, JWS signed ES256 with a P-256 key whose kid is the RFC 7638 JWK thumbprint.
The signing key is created on first run at ~/.config/liberate-labs/shc-issuer-key.pem (keep it
private and reuse it); the public JWKS is written next to the card as jwks.json, in case you host it
at <iss>/.well-known/jwks.json.
"""
import base64
import hashlib
import json
import sys
import time
import zlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

DEFAULT_KEY = Path.home() / ".config" / "liberate-labs" / "shc-issuer-key.pem"

# Display unit -> UCUM code. Anything not listed is passed through (it should already be UCUM).
UCUM = {"ratio": "{ratio}", "K/uL": "10*3/uL", "M/uL": "10*6/uL", "10^3/uL": "10*3/uL",
        "10^6/uL": "10*6/uL", "mcIU/mL": "u[IU]/mL", "uIU/mL": "u[IU]/mL", "IU/L": "[IU]/L"}


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def load_key(path: Path):
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    print(f"created signing key {path}", file=sys.stderr)
    return key


def public_jwk(key):
    n = key.public_key().public_numbers()
    jwk = {"crv": "P-256", "kty": "EC", "x": b64u(n.x.to_bytes(32, "big")), "y": b64u(n.y.to_bytes(32, "big"))}
    thumb = json.dumps(jwk, separators=(",", ":"), sort_keys=True).encode()  # RFC 7638: crv,kty,x,y
    kid = b64u(hashlib.sha256(thumb).digest())
    return {**jwk, "kid": kid, "use": "sig", "alg": "ES256"}, kid


def quantity(value, unit):
    return {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": UCUM.get(unit, unit)}


def observation(o, ref):
    obs = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                  "code": "laboratory"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": o["loinc"], "display": o["display"]}]},
        "subject": {"reference": ref},
        "effectiveDateTime": o["date"],
        "valueQuantity": quantity(o["value"], o["unit"]),
    }
    rr = {k: quantity(o[k], o["unit"]) for k in ("low", "high") if o.get(k) is not None}
    if rr:
        obs["referenceRange"] = [rr]
    return obs


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    spec = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    key = load_key(Path(sys.argv[sys.argv.index("--key") + 1]) if "--key" in sys.argv else DEFAULT_KEY)
    jwk, kid = public_jwk(key)

    p = spec["patient"]
    patient = {"resourceType": "Patient", "name": [{"family": p["family"], "given": p["given"]}]}
    if p.get("birthDate"):
        patient["birthDate"] = p["birthDate"]
    entries = [{"fullUrl": "resource:0", "resource": patient}]
    for i, o in enumerate(spec["observations"], start=1):
        entries.append({"fullUrl": f"resource:{i}", "resource": observation(o, "resource:0")})

    payload = {
        "iss": spec["iss"],
        "nbf": int(time.time()),
        "vc": {
            "type": ["https://smarthealth.cards#health-card", "https://smarthealth.cards#laboratory"],
            "credentialSubject": {"fhirVersion": "4.0.1",
                                  "fhirBundle": {"resourceType": "Bundle", "type": "collection", "entry": entries}},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw DEFLATE, as the spec requires
    deflated = comp.compress(raw) + comp.flush()
    header = {"zip": "DEF", "alg": "ES256", "kid": kid}
    signing_input = f"{b64u(json.dumps(header, separators=(',', ':')).encode())}.{b64u(deflated)}"
    der = key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    jws = f"{signing_input}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"

    out.write_text(json.dumps({"verifiableCredential": [jws]}))
    out.with_name("jwks.json").write_text(json.dumps({"keys": [jwk]}, indent=2))
    print(f"{out}: {len(spec['observations'])} observations, JWS {len(jws)} chars, kid {kid}")


if __name__ == "__main__":
    main()
