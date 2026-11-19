"""Offline issuer. Never package a private key with the application."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import licensing
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

parser = argparse.ArgumentParser()
commands = parser.add_subparsers(dest='command', required=True)
init = commands.add_parser('init')
init.add_argument('private_key', type=Path)
issue = commands.add_parser('issue')
issue.add_argument('private_key', type=Path)
issue.add_argument('customer')
issue.add_argument('purchased_version')
issue.add_argument('--trial-days', type=int, choices=[0, 30], default=0)
args = parser.parse_args()
if args.command == 'init':
    signer = ec.generate_private_key(ec.SECP256R1())
    with args.private_key.open('xb') as stream:
        stream.write(signer.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    print(signer.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), end='')
else:
    signer = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
    print(licensing.issue(signer, args.customer, args.purchased_version, args.trial_days))
