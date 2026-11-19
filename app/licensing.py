"""Offline signed PoolMarshall grants, following SentinelWatch's P256 format."""
import base64
import json
import re
import uuid
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

PRODUCT = 'PoolMarshall'

def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*\.[0-9]+\.[0-9]+', value):
        raise ValueError('Enter a three-part version, for example 1.1.0.')
    return tuple(map(int, value.split('.')))

def encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')

def decode(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)

def issue(signer, customer, purchased_version, trial_days=0):
    version(purchased_version)
    if not isinstance(customer, str) or not customer.strip() or len(customer) > 200 or trial_days not in (0, 30):
        raise ValueError('A customer (up to 200 characters) and trial days of 0 or 30 are required.')
    if not isinstance(signer, ec.EllipticCurvePrivateKey) or not isinstance(signer.curve, ec.SECP256R1):
        raise ValueError('A P256 private key is required.')
    payload = json.dumps(dict(Format=2 if trial_days else 1, Product=PRODUCT, LicenseId=str(uuid.uuid4()),
        Customer=customer.strip(), PurchasedVersion=purchased_version, TrialDays=trial_days), separators=(',', ':')).encode()
    r, s = utils.decode_dss_signature(signer.sign(payload, ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    return ('PM2.' if trial_days else 'PM1.') + encode(payload) + '.' + encode(signature)

def verify(key, public_key):
    try:
        if not isinstance(key, str) or len(key) > 4096:
            return None
        prefix, payload, signature = key.strip().split('.')
        if prefix not in ('PM1', 'PM2'):
            return None
        payload, signature = decode(payload), decode(signature)
        verifier = serialization.load_pem_public_key(public_key)
        if not isinstance(verifier, ec.EllipticCurvePublicKey) or not isinstance(verifier.curve, ec.SECP256R1) or len(signature) != 64:
            return None
        der = utils.encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big'))
        verifier.verify(der, payload, ec.ECDSA(hashes.SHA256()))
        grant = json.loads(payload)
        trial = prefix == 'PM2'
        if grant['Product'] != PRODUCT or type(grant['Format']) is not int or grant['Format'] != (2 if trial else 1) or type(grant['TrialDays']) is not int or grant['TrialDays'] != (30 if trial else 0):
            return None
        if not uuid.UUID(grant['LicenseId']).int or not isinstance(grant['Customer'], str) or not grant['Customer'].strip() or len(grant['Customer']) > 200:
            return None
        version(grant['PurchasedVersion'])
        return grant
    except (ValueError, TypeError, KeyError, AttributeError, InvalidSignature):
        return None

def covers(grant, current):
    return version(current)[0] <= version(grant['PurchasedVersion'])[0]
