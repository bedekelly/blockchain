import hashlib


def cryptographic_hash(block):
    hash_input = repr(list(sorted(block.items())))
    hash_input = hash_input.encode("utf-8")
    # Todo: can I just get the integer instead of a string?
    hash_value = hashlib.sha512(hash_input).hexdigest()
    hash_num = int(f"0x{hash_value}", 16)
    return hash_num
