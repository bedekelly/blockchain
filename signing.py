import secrets

from nacl import encoding, signing
from nacl.exceptions import BadSignatureError, ValueError as CryptoValueError


def generate_keypair():
    seed = secrets.token_bytes(32)
    signing_key = signing.SigningKey(seed)
    verify_key = signing_key.verify_key
    verify_key_hex = verify_key.encode(encoding.HexEncoder)
    return signing_key, verify_key_hex


def encode(transaction):
    return repr(transaction).encode("utf-8")


def sign_transaction(transaction, signing_key):
    trx_bytes = encode(transaction)
    signed = signing_key.sign(trx_bytes)
    signature = signed.signature
    return {**transaction, "signature": signature}


def strip_key(d, key):
    return {k: v for k, v in d.items() if k != key}


def verify_transaction(transaction):
    try:
        key = signing.VerifyKey(transaction["from"], encoder=encoding.HexEncoder)
    except CryptoValueError:
        return False
    except TypeError:
        breakpoint()

    signature = transaction["signature"]
    unsigned_transaction = strip_key(transaction, "signature")
    encoded_transaction = encode(unsigned_transaction)

    try:
        return key.verify(encoded_transaction, signature)
    except BadSignatureError:
        return False


if __name__ == "__main__":
    key, verify_key_hex = generate_keypair()
    transaction = {"amount": 1000, "to": "Bob", "from": verify_key_hex}
    signed_transaction = sign_transaction(transaction, key)
    assert verify_transaction(signed_transaction)
    signed_transaction["amount"] += 100
    assert not verify_transaction(signed_transaction)
    print("• Passed tests •")
