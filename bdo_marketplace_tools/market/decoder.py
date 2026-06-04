import struct
from collections import Counter
from functools import lru_cache


UINT = struct.Struct("<I")
HEADER = struct.Struct("<III")


class Node:
    __slots__ = ("c", "f", "left", "right")

    def __init__(self, char, freq, left=None, right=None):
        self.c = char
        self.f = freq
        self.left = left
        self.right = right

    def __lt__(self, other):
        return self.f < other.f

    def __le__(self, other):
        return self.f <= other.f

    def __repr__(self):
        return f'{self.c}:{self.f}'


class MinHeap:
    def __init__(self):
        self.arr = []

    def size(self):
        return len(self.arr)

    def push(self, obj):
        self.arr.append(obj)
        child_idx = self.size() - 1

        while True:
            parent_idx = (child_idx - 1) // 2
            if self.arr[parent_idx] <= self.arr[child_idx]:
                return

            self.arr[parent_idx], self.arr[child_idx] = self.arr[child_idx], self.arr[parent_idx]
            child_idx = parent_idx

            if child_idx <= 0:
                return

    def pop(self):
        obj = self.arr[0]

        last = self.arr.pop()
        if self.size() == 0:
            return obj
        self.arr[0] = last

        parent_idx = 0
        child_idx = 2 * parent_idx + 1
        while child_idx < self.size():
            if child_idx + 1 < self.size():
                if self.arr[child_idx + 1] < self.arr[child_idx]:
                    child_idx += 1

            if self.arr[parent_idx] <= self.arr[child_idx]:
                return obj

            self.arr[parent_idx], self.arr[child_idx] = self.arr[child_idx], self.arr[parent_idx]

            parent_idx = child_idx
            child_idx = 2 * child_idx + 1

        return obj


def make_tree(freqs):
    h = MinHeap()
    for c, f in freqs.items():
        h.push(Node(c, f))

    while h.size() > 1:
        a = h.pop()
        b = h.pop()
        n = Node(None, a.f + b.f, a, b)
        h.push(n)

    return h.pop()


def _is_leaf(node):
    return node.left is None and node.right is None


def _bit_string(packed, bits):
    bit_count = min(bits, len(packed) * 8)
    full_bytes, tail_bits = divmod(bit_count, 8)
    output = [f"{byte:08b}" for byte in packed[:full_bytes]]
    if tail_bits:
        output.append(f"{packed[full_bytes]:08b}"[:tail_bits])
    return "".join(output)


def _decode_tree_bits(tree, freqs, packed, bits):
    expected_chars = sum(freqs.values())
    if _is_leaf(tree):
        return tree.c * expected_chars

    bit_count = min(bits, len(packed) * 8)
    if bit_count == 0:
        return ""

    unpacked = [""] * expected_chars if expected_chars else []
    output_pos = 0
    node = tree
    full_bytes, tail_bits = divmod(bit_count, 8)
    total_bytes = full_bytes + (1 if tail_bits else 0)

    for byte_index in range(total_bytes):
        byte = packed[byte_index]
        bits_in_byte = tail_bits if tail_bits and byte_index == full_bytes else 8
        mask = 0x80
        for _ in range(bits_in_byte):
            node = node.right if byte & mask else node.left
            if node is None:
                raise ValueError(f'invalid tree: dead end while walking, {unpacked=}')
            if _is_leaf(node):
                if output_pos < expected_chars:
                    unpacked[output_pos] = node.c
                else:
                    unpacked.append(node.c)
                output_pos += 1
                node = tree
            mask >>= 1

    if node is not tree:
        raise ValueError(f'invalid tree: out of message bounds, {unpacked=}')

    if output_pos == len(unpacked):
        return "".join(unpacked)
    return "".join(unpacked[:output_pos])


def decode(tree, freqs, packed, bits, verbose=False, check_stats=False):
    if verbose:
        print(_bit_string(packed, bits))

    unpacked = _decode_tree_bits(tree, freqs, packed, bits)

    if check_stats:
        stats = Counter(unpacked)
        for c, f in freqs.items():
            if stats[c] != f:
                raise ValueError(f"incorrect '{c}' freq: header={f} processed={stats[c]}, {unpacked=}")

    return unpacked


class _DecodePlan:
    __slots__ = ("tree", "full_transitions", "state_nodes", "expected_chars")

    def __init__(self, tree, full_transitions, state_nodes, expected_chars):
        self.tree = tree
        self.full_transitions = full_transitions
        self.state_nodes = state_nodes
        self.expected_chars = expected_chars


def _collect_internal_nodes(root):
    nodes = []

    def walk(node):
        if _is_leaf(node):
            return
        nodes.append(node)
        walk(node.left)
        walk(node.right)

    walk(root)
    return nodes


def _advance_bits(root, start, byte, bit_count):
    node = start
    chars = []
    append = chars.append
    mask = 0x80
    for _ in range(bit_count):
        node = node.right if byte & mask else node.left
        if node is None:
            raise ValueError("invalid tree: dead end while building decoder table")
        if _is_leaf(node):
            append(node.c)
            node = root
        mask >>= 1

    return "".join(chars), node


@lru_cache(maxsize=16)
def _decode_plan(freq_items):
    freqs = dict(freq_items)
    tree = make_tree(freqs)
    expected_chars = sum(freqs.values())
    internal_nodes = _collect_internal_nodes(tree)
    if not internal_nodes:
        return _DecodePlan(tree, (), (), expected_chars)

    state_by_node = {node: index for index, node in enumerate(internal_nodes)}
    full_transitions = []
    for start in internal_nodes:
        row = []
        for byte in range(256):
            chars, next_node = _advance_bits(tree, start, byte, 8)
            row.append((chars, state_by_node[next_node]))
        full_transitions.append(tuple(row))

    return _DecodePlan(tree, tuple(full_transitions), tuple(internal_nodes), expected_chars)


def _decode_with_plan(plan, packed, bits):
    if not plan.full_transitions:
        return plan.tree.c * plan.expected_chars

    bit_count = min(bits, len(packed) * 8)
    if bit_count == 0:
        return ""

    chunks = []
    append = chunks.append
    state = 0
    full_bytes, tail_bits = divmod(bit_count, 8)

    for byte in packed[:full_bytes]:
        chars, state = plan.full_transitions[state][byte]
        if chars:
            append(chars)

    if tail_bits:
        chars, next_node = _advance_bits(plan.tree, plan.state_nodes[state], packed[full_bytes], tail_bits)
        if chars:
            append(chars)
        if next_node is not plan.tree:
            raise ValueError("invalid tree: out of message bounds")
        state = 0

    if state != 0:
        raise ValueError("invalid tree: out of message bounds")

    return "".join(chunks)


def read(file, fmt):
    i = struct.calcsize(fmt)
    ret = struct.unpack(fmt, file.read(i))
    if type(ret) == tuple and len(ret) == 1:
        return ret[0]
    return ret


def get_freqs(file):
    _file_len, _always0, chars_count = read(file, 'III')
    freqs = {}
    for i in range(chars_count):
        count = read(file, 'I')
        char = read(file, 'cxxx').decode('ascii')
        freqs[char] = count
    return freqs


def unpack_file(file):
    freqs = get_freqs(file)
    plan = _decode_plan(tuple(freqs.items()))

    packed_bits, packed_bytes, _unpacked_bytes = read(file, 'III')

    packed = file.read(packed_bytes)
    return _decode_with_plan(plan, packed, packed_bits)


def _unpack_bytes(data):
    view = memoryview(data)
    offset = 0
    _file_len, _always0, chars_count = HEADER.unpack_from(view, offset)
    offset += HEADER.size

    freq_items = []
    for _ in range(chars_count):
        count = UINT.unpack_from(view, offset)[0]
        offset += UINT.size
        char = bytes(view[offset:offset + 1]).decode("ascii")
        offset += UINT.size
        freq_items.append((char, count))

    packed_bits, packed_bytes, _unpacked_bytes = HEADER.unpack_from(view, offset)
    offset += HEADER.size
    packed = view[offset:offset + packed_bytes]
    return _decode_with_plan(_decode_plan(tuple(freq_items)), packed, packed_bits)


def unpack(data):
    if isinstance(data, (bytes, bytearray, memoryview)):
        return _unpack_bytes(data)

    return unpack_file(data)


if __name__ == "__main__":
    test = bytes.fromhex('81 00 00 00 00 00 00 00 0B 00 00 00 06 00 00 00 2D 00 00 00 09 00 00 00 30 00 00 00 03 00 00 00 31 00 00 00 03 00 00 00 32 00 00 00 02 00 00 00 33 00 00 00 02 00 00 00 34 00 00 00 06 00 00 00 35 00 00 00 03 00 00 00 37 00 00 00 04 00 00 00 38 00 00 00 01 00 00 00 39 00 00 00 02 00 00 00 7C 00 00 00 85 00 00 00 11 00 00 00 29 00 00 00 D3 0C 78 90 FB 1D 0E 6E 4B 4C 35 DF 17 75 BD AA 90')
    print(unpack(test))
